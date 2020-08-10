# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
# -*- coding: utf-8 -*-

from __future__ import unicode_literals
import frappe, erpnext
from frappe.utils import cint, cstr, formatdate, flt, getdate, nowdate, get_link_to_form
from frappe import _, throw
import frappe.defaults

from erpnext.assets.doctype.asset_category.asset_category import get_asset_category_account
from erpnext.controllers.buying_controller import BuyingController
from erpnext.accounts.party import get_party_account, get_due_date
from erpnext.accounts.utils import get_account_currency, get_fiscal_year
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import update_billed_amount_based_on_po
from erpnext.stock import get_warehouse_account_map
from erpnext.accounts.general_ledger import make_gl_entries, merge_similar_entries, make_reverse_gl_entries
from erpnext.accounts.doctype.gl_entry.gl_entry import update_outstanding_amt
from erpnext.buying.utils import check_on_hold_or_closed_status
from erpnext.accounts.general_ledger import get_round_off_account_and_cost_center
from erpnext.assets.doctype.asset.asset import get_asset_account, is_cwip_accounting_enabled
from frappe.model.mapper import get_mapped_doc
from six import iteritems
from erpnext.accounts.doctype.sales_invoice.sales_invoice import validate_inter_company_party, update_linked_doc,\
	unlink_inter_company_doc
from erpnext.accounts.doctype.tax_withholding_category.tax_withholding_category import get_party_tax_withholding_details
from erpnext.accounts.deferred_revenue import validate_service_stop_date
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import get_item_account_wise_additional_cost

form_grid_templates = {
	"items": "templates/form_grid/item_grid.html"
}

class PurchaseInvoiceRecord(BuyingController):
	def __init__(self, *args, **kwargs):
		super(PurchaseInvoiceRecord, self).__init__(*args, **kwargs)
		self.status_updater = [{
			'source_dt': 'Purchase Invoice Record Item',
			'target_field': 'billed_amt',
			'target_ref_field': 'amount',
			'target_dt': 'Purchase Invoice Item',
			'join_field': 'pi_detail',
			'target_parent_dt': 'Purchase Invoice',
			'target_parent_field': 'per_billed',
			'source_field': 'amount',
			'percent_join_field': 'purchase_invoice',
			'status_field': 'billing_status',
			'keyword': 'Billed',
			'overflow_type': 'billing'
		}, {
			'source_dt': 'Purchase Taxes and Charges',
			'target_field': 'billed_amt',
			'target_ref_field': 'tax_amount',
			'target_dt': 'Purchase Taxes and Charges',
			'join_field': 'pt_detail',
			'source_field': 'tax_amount',
		}]

	def onload(self):
		super(PurchaseInvoiceRecord, self).onload()
		supplier_tds = frappe.db.get_value("Supplier", self.supplier, "tax_withholding_category")
		self.set_onload("supplier_tds", supplier_tds)

	def before_save(self):
		if not self.on_hold:
			self.release_date = ''

	def validate(self):
		super(PurchaseInvoiceRecord, self).validate()

		# apply tax withholding only if checked and applicable
		self.set_tax_withholding()

		if not self.is_return:
			self.validate_supplier_invoice()

		# validate cash purchase
		if (self.is_paid == 1):
			self.validate_cash()

		self.validate_release_date()
		self.check_conversion_rate()
		self.validate_credit_to_acc()
		self.check_on_hold_or_closed_status()
		self.validate_with_previous_doc()
		self.validate_uom_is_integer("uom", "qty")
		self.validate_uom_is_integer("stock_uom", "stock_qty")
		self.validate_write_off_account()
		self.create_remarks()
		self.set_status()

	def validate_release_date(self):
		if self.release_date and getdate(nowdate()) >= getdate(self.release_date):
			frappe.throw(_('Release date must be in the future'))

	def validate_cash(self):
		if not self.cash_bank_account and flt(self.paid_amount):
			frappe.throw(_("Cash or Bank Account is mandatory for making payment entry"))

		if (flt(self.paid_amount) + flt(self.write_off_amount)
			- flt(self.get("rounded_total") or self.grand_total)
			> 1/(10**(self.precision("base_grand_total") + 1))):

			frappe.throw(_("""Paid amount + Write Off Amount can not be greater than Grand Total"""))

	def create_remarks(self):
		if not self.remarks:
			if self.bill_no and self.bill_date:
				self.remarks = _("Against Supplier Invoice {0} dated {1}").format(self.bill_no,
					formatdate(self.bill_date))
			else:
				self.remarks = _("No Remarks")

	def set_missing_values(self, for_validate=False):
		if not self.credit_to:
			self.credit_to = get_party_account("Supplier", self.supplier, self.company)
			self.party_account_currency = frappe.db.get_value("Account", self.credit_to, "account_currency", cache=True)
		if not self.due_date:
			self.due_date = get_due_date(self.posting_date, "Supplier", self.supplier, self.company,  self.bill_date)

		super(PurchaseInvoiceRecord, self).set_missing_values(for_validate)

	def check_conversion_rate(self):
		default_currency = erpnext.get_company_currency(self.company)
		if not default_currency:
			throw(_('Please enter default currency in Company Master'))
		if (self.currency == default_currency and flt(self.conversion_rate) != 1.00) or not self.conversion_rate or (self.currency != default_currency and flt(self.conversion_rate) == 1.00):
			throw(_("Conversion rate cannot be 0 or 1"))

	def validate_credit_to_acc(self):
		account = frappe.db.get_value("Account", self.credit_to,
			["account_type", "report_type", "account_currency"], as_dict=True)

		if account.report_type != "Balance Sheet":
			frappe.throw(_("Please ensure {} account is a Balance Sheet account. \
					You can change the parent account to a Balance Sheet account or select a different account.")
				.format(frappe.bold("Credit To")), title=_("Invalid Account"))

		if self.supplier and account.account_type != "Payable":
			frappe.throw(_("Please ensure {} account is a Payable account. \
					Change the account type to Payable or select a different account.")
				.format(frappe.bold("Credit To")), title=_("Invalid Account"))

		self.party_account_currency = account.account_currency

	def check_on_hold_or_closed_status(self):
		check_list = []

		for d in self.get('items'):
			if d.purchase_invoice and not d.purchase_invoice in check_list and not d.purchase_receipt:
				check_list.append(d.purchase_invoice)
				check_on_hold_or_closed_status('Purchase Invoice', d.purchase_invoice)

	def validate_with_previous_doc(self):
		super(PurchaseInvoiceRecord, self).validate_with_previous_doc({
			"Purchase Invoice": {
				"ref_dn_field": "purchase_invoice",
				"compare_fields": [["supplier", "="], ["company", "="], ["currency", "="]],
			},
			"Purchase Invoice Item": {
				"ref_dn_field": "pi_detail",
				"compare_fields": [["project", "="], ["item_code", "="], ["uom", "="]],
				"is_child_table": True,
				"allow_duplicate_prev_row_id": True
			},
			"Purchase Taxes And Charges": {
				"ref_dn_field": "pt_detail",
				"compare_fields": [["account_head", "="], ["charge_type", "="]],
				"is_child_table": True,
				"allow_duplicate_prev_row_id": True
			},
		})

		if cint(frappe.db.get_single_value('Buying Settings', 'maintain_same_rate')) and not self.is_return:
			self.validate_rate_with_reference_doc([
				["Purchase Invoice", "purchase_invoice", "pi_detail"],
			])

	def validate_write_off_account(self):
		if self.write_off_amount and not self.write_off_account:
			throw(_("Please enter Write Off Account"))

	def check_prev_docstatus(self):
		for d in self.get('items'):
			if d.purchase_invoice:
				submitted = frappe.db.sql("select name from `tabPurchase Invoice` where docstatus = 1 and name = %s", d.purchase_invoice)
				if not submitted:
					frappe.throw(_("Purchase Invoice {0} is not submitted").format(d.purchase_invoice))

	def on_submit(self):
		self.check_prev_docstatus()
		self.update_prevdoc_status()

		frappe.get_doc('Authorization Control').validate_approving_authority(self.doctype,
			self.company, self.base_grand_total)

	def on_cancel(self):
		self.check_on_hold_or_closed_status()
		self.update_prevdoc_status()

		frappe.db.set(self, 'status', 'Cancelled')

	def validate_supplier_invoice(self):
		if self.bill_date:
			if getdate(self.bill_date) > getdate(self.posting_date):
				frappe.throw(_("Supplier Invoice Date cannot be greater than Posting Date"))

		if self.bill_no:
			if cint(frappe.db.get_single_value("Accounts Settings", "check_supplier_invoice_uniqueness")):
				fiscal_year = get_fiscal_year(self.posting_date, company=self.company, as_dict=True)

				pi = frappe.db.sql('''select name from `tabPurchase Invoice`
					where
						bill_no = %(bill_no)s
						and supplier = %(supplier)s
						and name != %(name)s
						and docstatus < 2
						and posting_date between %(year_start_date)s and %(year_end_date)s''', {
							"bill_no": self.bill_no,
							"supplier": self.supplier,
							"name": self.name,
							"year_start_date": fiscal_year.year_start_date,
							"year_end_date": fiscal_year.year_end_date
						})

				if pi:
					pi = pi[0][0]
					frappe.throw(_("Supplier Invoice No exists in Purchase Invoice {0}").format(pi))

	def update_billing_status_in_pr(self, update_modified=True):
		updated_pr = []
		for d in self.get("items"):
			if d.pr_detail:
				billed_amt = frappe.db.sql("""select sum(amount) from `tabPurchase Invoice Item`
					where pr_detail=%s and docstatus=1""", d.pr_detail)
				billed_amt = billed_amt and billed_amt[0][0] or 0
				frappe.db.set_value("Purchase Receipt Item", d.pr_detail, "billed_amt", billed_amt, update_modified=update_modified)
				updated_pr.append(d.purchase_receipt)
			elif d.po_detail:
				updated_pr += update_billed_amount_based_on_po(d.po_detail, update_modified)

		for pr in set(updated_pr):
			frappe.get_doc("Purchase Receipt", pr).update_billing_percentage(update_modified=update_modified)

	def on_recurring(self, reference_doc, auto_repeat_doc):
		self.due_date = None

	def block_invoice(self, hold_comment=None, release_date=None):
		self.db_set('on_hold', 1)
		self.db_set('hold_comment', cstr(hold_comment))
		self.db_set('release_date', release_date)

	def unblock_invoice(self):
		self.db_set('on_hold', 0)
		self.db_set('release_date', None)

	def set_tax_withholding(self):
		if not self.apply_tds:
			return

		tax_withholding_details = get_party_tax_withholding_details(self, self.tax_withholding_category)

		if not tax_withholding_details:
			return

		accounts = []
		for d in self.taxes:
			if d.account_head == tax_withholding_details.get("account_head"):
				d.update(tax_withholding_details)
			accounts.append(d.account_head)

		if not accounts or tax_withholding_details.get("account_head") not in accounts:
			self.append("taxes", tax_withholding_details)

		to_remove = [d for d in self.taxes
			if not d.tax_amount and d.account_head == tax_withholding_details.get("account_head")]

		for d in to_remove:
			self.remove(d)

		# calculate totals again after applying TDS
		self.calculate_taxes_and_totals()

	def set_status(self, update=False, status=None, update_modified=True):
		if self.is_new():
			if self.get('amended_from'):
				self.status = 'Draft'
			return

		precision = self.precision("outstanding_amount")
		outstanding_amount = flt(self.outstanding_amount, precision)
		due_date = getdate(self.due_date)
		nowdate = getdate()

		if not status:
			if self.docstatus == 2:
				status = "Cancelled"
			elif self.docstatus == 1:
				self.status = "Billed"
			else:
				self.status = "Draft"

		if update:
			self.db_set('status', self.status, update_modified = update_modified)