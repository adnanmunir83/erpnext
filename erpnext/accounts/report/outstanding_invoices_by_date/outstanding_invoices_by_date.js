// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Outstanding Invoices by Date"] = {
	"filters": [
	{	"fieldname":"fdate",
		"label": __("From Date"),
		"fieldtype": "Date",	
	 	"default": get_today(), 
		"reqd": 1
	}  ,
	{
		"fieldname":"tdate",
		"label": __("To Date"),
		"fieldtype": "Date",	
		 "default": get_today(), 
		"reqd": 1
	}  ,
	{
		"fieldname":"customer",
		"label": __("Customer"),
		"fieldtype": "Link",	
		 "options": "Customer"	
	}		

	]
}
