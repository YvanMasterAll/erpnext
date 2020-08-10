// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

// render
frappe.listview_settings['Purchase Invoice Record'] = {
	add_fields: ["supplier", "supplier_name", "base_grand_total", "outstanding_amount", "due_date", "company",
		"currency", "is_return", "release_date", "on_hold"],
	get_indicator: function(doc) {
		var status_color = {
			"Draft": "grey",
			"Unpaid": "orange",
			"Billed": "green",
			"Paid": "green",
			"Return": "darkgrey",
			"Credit Note Issued": "darkgrey",
			"Unpaid and Discounted": "orange",
			"Overdue and Discounted": "red",
			"Overdue": "red"

		};
		return [__(doc.status), status_color[doc.status], "status,=,"+doc.status];
	}
};