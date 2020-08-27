# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe, erpnext
import frappe.defaults
from frappe.utils import cint, flt, add_months, today, date_diff, getdate, add_days, cstr, nowdate
from frappe import _, msgprint, throw
from erpnext.accounts.party import get_party_account, get_due_date
from frappe.model.mapper import get_mapped_doc
from erpnext.accounts.doctype.sales_invoice.pos import update_multi_mode_option

from erpnext.controllers.selling_controller import SellingController
from erpnext.accounts.utils import get_account_currency
from erpnext.stock.doctype.delivery_note.delivery_note import update_billed_amount_based_on_so
from erpnext.projects.doctype.timesheet.timesheet import get_projectwise_timesheet_data
from erpnext.assets.doctype.asset.depreciation \
	import get_disposal_account_and_cost_center, get_gl_entries_on_asset_disposal
from erpnext.stock.doctype.batch.batch import set_batch_nos
from erpnext.stock.doctype.serial_no.serial_no import get_serial_nos, get_delivery_note_serial_no
from erpnext.setup.doctype.company.company import update_company_current_month_sales
from erpnext.accounts.general_ledger import get_round_off_account_and_cost_center
from erpnext.accounts.doctype.loyalty_program.loyalty_program import \
	get_loyalty_program_details_with_points, get_loyalty_details, validate_loyalty_points
from erpnext.accounts.deferred_revenue import validate_service_stop_date

from erpnext.healthcare.utils import manage_invoice_submit_cancel

from six import iteritems

form_grid_templates = {
	"items": "templates/form_grid/item_grid.html"
}

class SalesInvoiceRecord(SellingController):
	def __init__(self, *args, **kwargs):
		super(SalesInvoiceRecord, self).__init__(*args, **kwargs)
		self.status_updater = [{
			'source_dt': 'Sales Invoice Record Item',
			'target_field': 'billed_amt',
			'target_ref_field': 'amount',
			'target_dt': 'Sales Invoice Item',
			'join_field': 'si_detail',
			'target_parent_dt': 'Sales Invoice',
			'target_parent_field': 'per_billed',
			'source_field': 'amount',
			'join_field': 'si_detail',
			'percent_join_field': 'sales_invoice_reference',
			'status_field': 'billing_status',
			'keyword': 'Billed',
			'overflow_type': 'billing'
		}]

	def set_indicator(self):
		"""Set indicator for portal"""
		if self.outstanding_amount < 0:
			self.indicator_title = _("Credit Note Issued")
			self.indicator_color = "darkgrey"
		elif self.outstanding_amount > 0 and getdate(self.due_date) >= getdate(nowdate()):
			self.indicator_color = "orange"
			self.indicator_title = _("Unpaid")
		elif self.outstanding_amount > 0 and getdate(self.due_date) < getdate(nowdate()):
			self.indicator_color = "red"
			self.indicator_title = _("Overdue")
		elif cint(self.is_return) == 1:
			self.indicator_title = _("Return")
			self.indicator_color = "darkgrey"
		else:
			self.indicator_color = "green"
			self.indicator_title = _("Paid")

	def validate(self):
		super(SalesInvoiceRecord, self).validate()

		self.validate_with_previous_doc()
		self.validate_uom_is_integer("uom", "qty")
		self.check_sales_invoice_on_hold_or_close("sales_invoice_reference")
		self.add_remarks()
		self.validate_item_cost_centers()

		self.set_status()

	def on_submit(self):
		self.check_prev_docstatus()

		self.update_prevdoc_status()

	def before_cancel(self):
		return

	def on_cancel(self):
		self.update_prevdoc_status()

		frappe.db.set(self, 'status', 'Cancelled')

	def on_update(self):
		return

	def check_prev_docstatus(self):
		for d in self.get('items'):
			if d.sales_invoice_reference and frappe.db.get_value("Sales Invoice", d.sales_invoice_reference, "docstatus") != 1:
				frappe.throw(_("Sales Invoice {0} is not submitted").format(d.sales_invoice_reference))

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

	def validate_auto_set_posting_time(self):
		# Don't auto set the posting date and time if invoice is amended
		if self.is_new() and self.amended_from:
			self.set_posting_time = 1

		self.validate_posting_time()
	
	def validate_with_previous_doc(self):
		super(SalesInvoiceRecord, self).validate_with_previous_doc({
			# Change: 因为销售发票和发票已经分道扬镳，所以就没有必要验证属性
			# "Sales Invoice": {
			# 	"ref_dn_field": "sales_invoice",
			# 	"compare_fields": [["customer", "="], ["company", "="], ["project", "="], ["currency", "="]]
			# },
			"Sales Invoice Item": {
				"ref_dn_field": "si_detail",
				"compare_fields": [["item_code", "="], ["uom", "="], ["conversion_factor", "="]],
				"is_child_table": True,
				"allow_duplicate_prev_row_id": True
			},
			# Change: 这里添加子表验证，本地测试没有问题，但是线上却报错：Invalid reference {0} {1},无效的参考{0} {1}
			# "Sales Taxes And Charges": {
			# 	"ref_dn_field": "st_detail",
			# 	"compare_fields": [["account_head", "="], ["charge_type", "="]],
			# 	"is_child_table": True
			# },
		})

	def add_remarks(self):
		if not self.remarks: self.remarks = _('No Remarks')

	def validate_fixed_asset(self):
		for d in self.get("items"):
			if d.is_fixed_asset and d.meta.get_field("asset") and d.asset:
				asset = frappe.get_doc("Asset", d.asset)
				if self.doctype == "Sales Invoice Record" and self.docstatus == 1:
					if self.update_stock:
						frappe.throw(_("'Update Stock' cannot be checked for fixed asset sale"))

					elif asset.status in ("Scrapped", "Cancelled", "Sold"):
						frappe.throw(_("Row #{0}: Asset {1} cannot be submitted, it is already {2}").format(d.idx, d.asset, asset.status))

	def set_income_account_for_fixed_assets(self):
		disposal_account = depreciation_cost_center = None
		for d in self.get("items"):
			if d.is_fixed_asset:
				if not disposal_account:
					disposal_account, depreciation_cost_center = get_disposal_account_and_cost_center(self.company)

				d.income_account = disposal_account
				if not d.cost_center:
					d.cost_center = depreciation_cost_center

	def validate_item_cost_centers(self):
		for item in self.items:
			cost_center_company = frappe.get_cached_value("Cost Center", item.cost_center, "company")
			if cost_center_company != self.company:
				frappe.throw(_("Row #{0}: Cost Center {1} does not belong to company {2}").format(frappe.bold(item.idx), frappe.bold(item.cost_center), frappe.bold(self.company)))