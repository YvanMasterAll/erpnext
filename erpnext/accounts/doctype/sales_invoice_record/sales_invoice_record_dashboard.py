from __future__ import unicode_literals
from frappe import _

def get_data():
	return {
		'fieldname': 'sales_invoice_record',
		'non_standard_fieldnames': {},
		'internal_links': {
			'Sales Invoice': ['items', 'sales_invoice']
		},
		'transactions': [
			{
				'label': _('Reference'),
				'items': ['Sales Invoice']
			}
		]
	}