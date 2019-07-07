// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
/* eslint-disable */
frappe.require("assets/erpnext/js/financial_statements.js", function() {
	frappe.query_reports["P&L by CostCenter"] = $.extend({},
		erpnext.financial_statements);

	frappe.query_reports["P&L by CostCenter"] ["filters"].push(
		{
			"fieldname":"cost_center",
			"label": __("Cost Center"),
			"fieldtype": "Link",
			"options": "Cost Center"
		},
		{
			"fieldname":"project",
			"label": __("Project"),
			"fieldtype": "Link",
			"options": "Project"
		}
	);
});