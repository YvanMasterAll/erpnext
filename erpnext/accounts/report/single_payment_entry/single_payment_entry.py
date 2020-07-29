# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
from frappe import _

# TODO: 参考Payment Period Based On Invoice Date Report和Trial Balance Report

def execute(filters=None):
	if not filters:
		filters = {}

	columns = get_columns()

	payments = frappe.db.sql("""select name from `tabPayment Entry`""")
	print(payments)

	return columns, payments

def get_columns():
	return [
		_("Title") + "::140",
	]