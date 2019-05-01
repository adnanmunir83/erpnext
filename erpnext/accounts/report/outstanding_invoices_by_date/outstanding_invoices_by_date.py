# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _

def execute(filters=None):
	
	if not filters: filters = {}
	
		
	columns = get_columns()
	data = get_data(filters)

	return columns, data

def get_data(filters):
	customer_condition = ""
	if filters.get("customer"):
		customer_condition = " and customer='" + filters.get("customer") + "'"

	return frappe.db.sql("""
			select 
			name , posting_date , customer , grand_total , paid_amount , 
			outstanding_amount , company

			from `tabSales Invoice` 

			where 
			grand_total-1>paid_amount
			and outstanding_amount >0
			and docstatus=1
			{0}
			and posting_date >= %(fdate)s
			and posting_date <= %(tdate)s
			order by customer""".format(customer_condition), filters, as_dict=False)

def get_columns():
	"""return columns"""

	columns = [
		_("Invoice No")+":Link/Sales Invoice:100",
		_("Date")+":Date:100",
		_("Customer")+":Link/Customer:200",
		_("Total")+":Float:100",	
		_("Paid")+":Float:100",
		_("Outstanding")+":Float:100",	
		_("Company")+":Link/Company:100"
	]

	return columns