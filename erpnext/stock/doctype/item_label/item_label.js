// Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Item Label', {

	refresh: function(frm) {

        frm.set_query("price_list","items", function() {
	        return {
                "filters": {"selling": 1   }
            }
        });
	},

	on_submit: function(frm) {
            $.each(frm.doc.items || [], function(i, v) { // for each item on table do this
                var oldprice;
                frappe.call({
                    method: "frappe.client.get_list",
                    args: {
                        doctype: "Item Price",
                        filters: [
                            ['price_list', "=", v.price_list],
                            ["item_code", "=", v.item_code],
                        ],
                        fields: ["price_list_rate","name"]
                    },
                    callback: function(r) { // do this to found price list doc
                        oldprice = (r.message[0].price_list_rate);
                        var namelist = r.message[0].name
                        // console.log(oldprice)
                        if (oldprice && oldprice != v.item_price) {

                            frappe.db.set_value("Item Price", namelist, "price_list_rate", v.item_price)
                            //frappe.confirm(
                             //   `Do you want to update the price of item ${v.item_code} having price ${ oldprice } with ${ v.item_price} in the price list ${v.price_list} ?`, //ask something to update price
                             //   function() { // do this if ok
                              //      frappe.db.set_value("Item Price", namelist, "price_list_rate", v.item_price)
                              //  },
                              //  function() { // do nothing if cancel

                               // }

                           // )
                        }
                    }
                });
            })
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
