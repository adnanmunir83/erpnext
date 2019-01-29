// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Sales Order With Payment"] = {
	"filters": [
        {
            "fieldname":"company",
            "label": __("Company"),
            "fieldtype": "Link",
            "options": "Company",
            "reqd": 1
        } ,
        {
            "fieldname":"fdate",
            "label": __("From Date"),
            "fieldtype": "Date",
             "default": get_today(),
            "reqd": 1
        } ,
        {
            "fieldname":"tdate",
            "label": __("To Date"),
            "fieldtype": "Date",
             "default": get_today(),
            "reqd": 1
        }
    ]
}