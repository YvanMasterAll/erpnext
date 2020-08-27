// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

// print heading
cur_frm.pformat.print_heading = 'Invoice';

{% include 'erpnext/selling/sales_common.js' %};


frappe.provide("erpnext.accounts");
erpnext.accounts.SalesInvoiceController = erpnext.selling.SellingController.extend({
	setup: function(doc) {
		this.setup_posting_date_time_check();
		this._super(doc);
	},
	onload: function() {
		var me = this;
		this._super();
	},

	refresh: function(doc, dt, dn) {
		const me = this;
		this._super();
		if(cur_frm.msgbox && cur_frm.msgbox.$wrapper.is(":visible")) {
			// hide new msgbox
			cur_frm.msgbox.hide();
		}

		this.frm.toggle_reqd("due_date", !this.frm.doc.is_return);
	},

	on_submit: function(doc, dt, dn) {
		var me = this;

		if (frappe.get_route()[0] != 'Form') {
			return
		}
	},

	items_add: function(doc, cdt, cdn) {
		var row = frappe.get_doc(cdt, cdn);
		this.frm.script_manager.copy_from_first_row("items", row, ["income_account", "cost_center"]);
	},

	set_dynamic_labels: function() {
		this._super();
		this.frm.events.hide_fields(this.frm)
	},

	items_on_form_rendered: function() {
		erpnext.setup_serial_no();
	},

	packed_items_on_form_rendered: function(doc, grid_row) {
		erpnext.setup_serial_no();
	},

	asset: function(frm, cdt, cdn) {
		var row = locals[cdt][cdn];
		if(row.asset) {
			frappe.call({
				method: erpnext.assets.doctype.asset.depreciation.get_disposal_account_and_cost_center,
				args: {
					"company": frm.doc.company
				},
				callback: function(r, rt) {
					frappe.model.set_value(cdt, cdn, "income_account", r.message[0]);
					frappe.model.set_value(cdt, cdn, "cost_center", r.message[1]);
				}
			})
		}
	}

});

// for backward compatibility: combine new and previous states
$.extend(cur_frm.cscript, new erpnext.accounts.SalesInvoiceController({frm: cur_frm}));

// Income Account in Details Table
// --------------------------------
cur_frm.set_query("income_account", "items", function(doc) {
	return{
		query: "erpnext.controllers.queries.get_income_account",
		filters: {'company': doc.company}
	}
});


// Cost Center in Details Table
// -----------------------------
cur_frm.fields_dict["items"].grid.get_field("cost_center").get_query = function(doc) {
	return {
		filters: {
			'company': doc.company,
			"is_group": 0
		}
	}
}

cur_frm.cscript.income_account = function(doc, cdt, cdn) {
	erpnext.utils.copy_value_in_all_rows(doc, cdt, cdn, "items", "income_account");
}

cur_frm.cscript.expense_account = function(doc, cdt, cdn) {
	erpnext.utils.copy_value_in_all_rows(doc, cdt, cdn, "items", "expense_account");
}

cur_frm.cscript.cost_center = function(doc, cdt, cdn) {
	erpnext.utils.copy_value_in_all_rows(doc, cdt, cdn, "items", "cost_center");
}

cur_frm.set_query("debit_to", function(doc) {
	return {
		filters: {
			'account_type': 'Receivable',
			'is_group': 0,
			'company': doc.company
		}
	}
});

cur_frm.set_query("asset", "items", function(doc, cdt, cdn) {
	var d = locals[cdt][cdn];
	return {
		filters: [
			["Asset", "item_code", "=", d.item_code],
			["Asset", "docstatus", "=", 1],
			["Asset", "status", "in", ["Submitted", "Partially Depreciated", "Fully Depreciated"]],
			["Asset", "company", "=", doc.company]
		]
	}
});

frappe.ui.form.on('Sales Invoice Record', {
	setup: function(frm){
		frm.add_fetch('customer', 'tax_id', 'tax_id');
		frm.add_fetch('payment_term', 'invoice_portion', 'invoice_portion'); 
		frm.add_fetch('payment_term', 'description', 'description');

		frm.set_query("sales_invoice_reference", "items", function(doc, cdt, cdn) {
			return { filters: { "customer": doc.customer } };
		});
		
		frm.set_query("item_code", "items", function(doc, cdt, cdn) {
			let row = locals[cdt][cdn]
			return { 
				query: "erpnext.accounts.doctype.sales_invoice_item.sales_invoice_item.get_items", 
				filters: { 
					"sales_invoice_reference": row.sales_invoice_reference
				}};
			}
		);

		frm.set_query("account_for_change_amount", function() {
			return {
				filters: {
					account_type: ['in', ["Cash", "Bank"]],
					company: frm.doc.company,
					is_group: 0
				}
			};
		});

		frm.set_query("cost_center", function() {
			return {
				filters: {
					company: frm.doc.company,
					is_group: 0
				}
			};
		});

		// expense account
		frm.fields_dict['items'].grid.get_field('expense_account').get_query = function(doc) {
			if (erpnext.is_perpetual_inventory_enabled(doc.company)) {
				return {
					filters: {
						'report_type': 'Profit and Loss',
						'company': doc.company,
						"is_group": 0
					}
				}
			}
		}

		frm.fields_dict['items'].grid.get_field('deferred_revenue_account').get_query = function(doc) {
			return {
				filters: {
					'root_type': 'Liability',
					'company': doc.company,
					"is_group": 0
				}
			}
		}
	},

	onload: function(frm) {
		frm.redemption_conversion_factor = null;
	},

	hide_fields: function(frm) {
		return
	},

	refresh: function(frm) {
		frm.set_df_property("patient", "hidden", 1);
		frm.set_df_property("patient_name", "hidden", 1);
		frm.set_df_property("ref_practitioner", "hidden", 1);
	},

	get_not_billed_item: function(frm) {
		frm.clear_table("items");
		var args = {
			"company": frm.doc.company,
			"party": frm.doc.customer,
			"party_type": "Customer"
		}
		frappe.call({
			method: 'erpnext.accounts.doctype.payment_entry.payment_entry.get_not_billed_item',
			args: {
				args: args
			},
			callback: function(r, rt) {
				if(r.message) {
					var billed_amt = frm.doc.billed_amt
					$.each(r.message, function(i, d) {
						if (billed_amt <= 0) { return false }
						var not_billed_amt = flt(d.amount - d.billed_amt)
						if (billed_amt < not_billed_amt) {
							not_billed_amt = billed_amt
						}
						billed_amt -= not_billed_amt
						var c = frm.add_child("items")
						Object.keys(d).forEach(key => {
							c[key] = d[key]
						})
						c.qty = not_billed_amt / flt(c.rate)
					})
					frm.cscript.calculate_taxes_and_totals()
					frm.refresh_fields()
				}
			}
		});
		refresh_field('items');
	}
})

var calculate_total_billing_amount =  function(frm) {
	var doc = frm.doc;

	doc.total_billing_amount = 0.0
	if(doc.timesheets) {
		$.each(doc.timesheets, function(index, data){
			doc.total_billing_amount += data.billing_amount
		})
	}

	refresh_field('total_billing_amount')
}