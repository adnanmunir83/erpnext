# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.utils import flt
from erpnext.accounts.report.financial_statements import (get_period_list, get_data)

def execute(filters=None):
	period_list = get_period_list(filters.from_fiscal_year, filters.to_fiscal_year,
		filters.periodicity, filters.accumulated_values, filters.company)

	data = []
	data = get_row_labels(period_list,
		period_list[0]["year_start_date"] ,
		period_list[0]["year_end_date"],filters.company)

	columns = []

	columns = get_columns(filters.periodicity, period_list, filters.accumulated_values, filters.company)
	return columns, data

def get_row_labels(period_list,from_date,to_date,company=None):
	data = frappe.db.sql("""select 	account ,cost_center from `tabGL Entry` where company=%(company)s
		and account in (select name from tabAccount where report_type = 'Profit and Loss' and docstatus<2)
		and posting_date >=  %(from_date)s and posting_date <=  %(to_date)s
		group by cost_center, account order by account""",
		{
			"company": company,
			"from_date": from_date,
			"to_date": to_date,
		},
		as_dict=1)
	data_in_list = []
	row_period = {}
	for period in period_list:
			row_period[period.key]=0
	for d in data:
		row = frappe._dict({
			"account": d.account,
			"cost_center":d.cost_center,
			"account_name":  d.account
			})
		row.update(row_period.copy())
		data_in_list.append(row)
	
	for period in period_list:
		data_with_balance = frappe.db.sql("""select 	account ,cost_center,Sum(debit)-Sum(credit) as balance from `tabGL Entry` where company=%(company)s
			and account in (select name from tabAccount where report_type = 'Profit and Loss' and docstatus<2)
			and posting_date >=  %(from_date)s and posting_date <=  %(to_date)s
			group by cost_center, account order by account""",
			{
				"company": company,
				"from_date": period.from_date,
				"to_date": period.to_date,
			},
			as_dict=1)
		for dwb in data_with_balance:
			for d in data_in_list:
				if dwb.account == d.account and dwb.cost_center == d.cost_center:
					d[period.key]= dwb.balance
					break
	return data_in_list
	


def get_columns(periodicity, period_list, accumulated_values=1, company=None):
	columns = [{
		"fieldname": "account",
		"label": _("Account"),
		"fieldtype": "Link",
		"options": "Account",
		"width": 300
	},
	{
		"fieldname": "cost_center",
		"label": _("Cost Center"),
		"fieldtype": "Link",
		"options": "Cost Center",
		"width": 300
	}
	]	
	for period in period_list:
		columns.append({
			"fieldname": period.key,
			"label": period.label,
			"fieldtype": "Currency",
			"options": "currency",
			"width": 150
		})	

	return columns
