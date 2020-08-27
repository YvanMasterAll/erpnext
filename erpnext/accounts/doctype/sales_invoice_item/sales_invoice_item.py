# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe

from frappe.model.document import Document
from erpnext.controllers.print_settings import print_settings_for_item_table

class SalesInvoiceItem(Document):
	def __setup__(self):
		print_settings_for_item_table(self)

# Change: 创建销售实际发票时根据物料的销售发票引用找到物料代码
@frappe.whitelist()
def get_items(doctype, txt, searchfield, start, page_len, filters):
	sales_invoice_reference = filters.get("sales_invoice_reference")
	if not sales_invoice_reference:
		return []

	return frappe.db.sql("""select item_code from `tabSales Invoice Item`
		where parent = %(sales_invoice_reference)s
		order by name limit %(start)s, %(page_len)s"""
		.format(), {
			'sales_invoice_reference': sales_invoice_reference,
			'start': start, 'page_len': page_len
		})
		
@frappe.whitelist()
def get_si_detail(sales_invoice_reference, item_code):
	return frappe.db.sql("""select name from `tabSales Invoice Item`
		where parent = %(sales_invoice_reference)s and item_code = %(item_code)s
		"""
		.format(), {
			'sales_invoice_reference': sales_invoice_reference,
			'item_code': item_code
		})
		
