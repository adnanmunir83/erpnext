// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Customer Statment"] = {
	"filters": [
		{
            "fieldname":"from_date",
            "label": __("From Date"),
            "fieldtype": "Date",	
	     	"default": get_today(), 
            "reqd": 1
        }  ,
		{
            "fieldname":"to_date",
            "label": __("To Date"),
            "fieldtype": "Date",	
	     	"default": get_today(), 
            "reqd": 1
        }  ,	
		{
			"fieldname":"customer",
			"label": __("Customer"),
			"fieldtype": "Link",
			"options" : "Customer",
			"reqd" : 1
		},
		{
			"fieldname":"invoice_type",
			"label": __("Invoice Type"),
			"fieldtype": "Select",
			"default": "UnPaid",
			"options": ["UnPaid","All"]
		}
	]
}
