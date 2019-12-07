// Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Item Label', {

	refresh: function(frm) {

        frm.set_query("price_list","items", function() {
	        return {
                "filters": {"selling": 1   }
            }
        });
	}
});

frappe.ui.form.on('Item Label Reference',
{
    item_code: function(frm, cdt, cdn)
    {
        var row = locals[cdt][cdn];
        frappe.call({
        	method: "frappe.client.get",
        	args: {
        		doctype: "Item Price",
        		filters: {
        			"price_list": row.price_list,
        			"item_code": row.item_code
        		}
        	},
        	callback: function (data) {
				row.item_price = data.message.price_list_rate;
				refresh_field("item_price", cdn, "items");
  	    	}
        })
     }
})
