from __future__ import unicode_literals
from frappe import _

def get_data():
	return {
		'fieldname': 'purchase_invoice_record',
		'non_standard_fieldnames': {},
		'internal_links': {
			'Purchase Invoice': ['items', 'purchase_invoice_reference']
		},
		'transactions': [
			{
				'label': _('Reference'),
				'items': ['Purchase Invoice']
			}
		]
	}