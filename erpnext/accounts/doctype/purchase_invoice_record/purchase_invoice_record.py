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
			'percent_join_field': 'purchase_invoice_reference',
			'status_field': 'billing_status',
			'keyword': 'Billed',
			'overflow_type': 'billing'
		}]

	def onload(self):
		super(PurchaseInvoiceRecord, self).onload()
		supplier_tds = frappe.db.get_value("Supplier", self.supplier, "tax_withholding_category")
		self.set_onload("supplier_tds", supplier_tds)

	def before_save(self):
		return

	def validate(self):
		super(PurchaseInvoiceRecord, self).validate()

		self.check_conversion_rate()
		self.check_on_hold_or_closed_status()
		self.validate_with_previous_doc()
		self.validate_uom_is_integer("uom", "qty")
		self.create_remarks()
		self.set_status()

	def create_remarks(self):
		if not self.remarks:
			self.remarks = _("No Remarks")
				

	def check_conversion_rate(self):
		default_currency = erpnext.get_company_currency(self.company)
		if not default_currency:
			throw(_('Please enter default currency in Company Master'))
		if (self.currency == default_currency and flt(self.conversion_rate) != 1.00) or not self.conversion_rate or (self.currency != default_currency and flt(self.conversion_rate) == 1.00):
			throw(_("Conversion rate cannot be 0 or 1"))

	def check_on_hold_or_closed_status(self):
		check_list = []

		for d in self.get('items'):
			if d.purchase_invoice_reference and not d.purchase_invoice_reference in check_list:
				check_list.append(d.purchase_invoice_reference)
				check_on_hold_or_closed_status('Purchase Invoice', d.purchase_invoice_reference)

	def validate_with_previous_doc(self):
		super(PurchaseInvoiceRecord, self).validate_with_previous_doc({
			"Purchase Invoice Item": {
				"ref_dn_field": "pi_detail",
				"compare_fields": [["project", "="], ["item_code", "="], ["uom", "="]],
				"is_child_table": True,
				"allow_duplicate_prev_row_id": True
			}
		})

		if cint(frappe.db.get_single_value('Buying Settings', 'maintain_same_rate')):
			self.validate_rate_with_reference_doc([
				["Purchase Invoice", "purchase_invoice", "pi_detail"],
			])

	def check_prev_docstatus(self):
		for d in self.get('items'):
			if d.purchase_invoice_reference:
				submitted = frappe.db.sql("select name from `tabPurchase Invoice` where docstatus = 1 and name = %s", d.purchase_invoice_reference)
				if not submitted:
					frappe.throw(_("Purchase Invoice {0} is not submitted").format(d.purchase_invoice_reference))

	def on_submit(self):
		self.check_prev_docstatus()
		self.update_prevdoc_status()

		frappe.get_doc('Authorization Control').validate_approving_authority(self.doctype,
			self.company, self.base_grand_total)

	def on_cancel(self):
		self.check_on_hold_or_closed_status()
		self.update_prevdoc_status()

		frappe.db.set(self, 'status', 'Cancelled')

	def set_status(self, update=False, status=None, update_modified=True):
		if self.is_new():
			if self.get('amended_from'):
				self.status = 'Draft'
			return

		if not status:
			if self.docstatus == 2:
				status = "Cancelled"
			elif self.docstatus == 1:
				self.status = "Billed"
			else:
				self.status = "Draft"

		if update:
			self.db_set('status', self.status, update_modified = update_modified)