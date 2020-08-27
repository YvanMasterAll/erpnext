// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("erpnext.accounts");
{% include 'erpnext/public/js/controllers/buying.js' %};

erpnext.accounts.PurchaseInvoiceRecord = erpnext.buying.BuyingController.extend({
	setup: function(doc) {
		this.setup_posting_date_time_check();
		this._super(doc);
	},
	
	onload: function() {
		this._super();
	},

	refresh: function(doc) {
		const me = this;
		this._super();

		hide_fields(this.frm.doc);
	},

	items_add: function(doc, cdt, cdn) {
		var row = frappe.get_doc(cdt, cdn);
		this.frm.script_manager.copy_from_first_row("items", row,
			["expense_account", "cost_center", "project"]);
	},

	on_submit: function() {
		return
	},

});

cur_frm.script_manager.make(erpnext.accounts.PurchaseInvoiceRecord);

// Hide Fields
// ------------
function hide_fields(doc) {
	return
}

cur_frm.fields_dict["items"].grid.get_field("cost_center").get_query = function(doc) {
	return {
		filters: {
			'company': doc.company,
			'is_group': 0
		}

	}
}

cur_frm.cscript.cost_center = function(doc, cdt, cdn){
	var d = locals[cdt][cdn];
	if(d.cost_center){
		var cl = doc.items || [];
		for(var i = 0; i < cl.length; i++){
			if(!cl[i].cost_center) cl[i].cost_center = d.cost_center;
		}
	}
	refresh_field('items');
}

cur_frm.fields_dict['items'].grid.get_field('project').get_query = function(doc, cdt, cdn) {
	return{
		filters:[
			['Project', 'status', 'not in', 'Completed, Cancelled']
		]
	}
}

frappe.ui.form.on("Purchase Invoice Record", {
	setup: function(frm) {
		frm.fields_dict['items'].grid.get_field('deferred_expense_account').get_query = function(doc) {
			return {
				filters: {
					'root_type': 'Asset',
					'company': doc.company,
					"is_group": 0
				}
			}
		}

		frm.set_query("cost_center", function() {
			return {
				filters: {
					company: frm.doc.company,
					is_group: 0
				}
			};
		});

		frm.set_query("purchase_invoice_reference", "items", function(doc, cdt, cdn) {
			return { filters: { "supplier": doc.supplier } };
		});
		
		frm.set_query("item_code", "items", function(doc, cdt, cdn) {
			let row = locals[cdt][cdn]
			return { 
				query: "erpnext.accounts.doctype.purchase_invoice_item.purchase_invoice_item.get_items", 
				filters: { 
					"purchase_invoice_reference": row.purchase_invoice_reference
				}};
			}
		);
	},

	onload: function(frm) {
		return
	},

	get_not_billed_item: function(frm) {
		frm.clear_table("items");
		var args = {
			"company": frm.doc.company,
			"party": frm.doc.supplier,
			"party_type": "Supplier"
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
