# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.utils import cint
from frappe import _

def execute(filters=None):
	if not filters: filters ={}

	invoice_type = filters.get("invoice_type")

	conditions = " docstatus=1 "	
	if filters.get("from_date"): conditions += " and posting_date>= '" + filters.get("from_date") + "'"
	if filters.get("to_date"): conditions += " and posting_date<='"+ filters.get("to_date") + "'"
	if filters.get("customer"): conditions += " and customer ='"+ filters.get("customer") + "'"
	if invoice_type == "UnPaid":
		conditions += """ and outstanding_amount > 0 """
	
	columns = get_columns()
	data = get_invoice_details(conditions)	
	
	return columns, data

def get_invoice_details(conditions):		
	return frappe.db.sql("""select
			name, posting_date, customer,			
			rounded_total, paid_amount,
			outstanding_amount
		from `tabSales Invoice` 
		where {0}		
		order by posting_date desc """.format(conditions), as_list=1)

def get_columns():
	return [
		_("Invoice") + ":Link/Sales Invoice:80",
		_("Date") + ":Date:80",
		_("Customer") + ":Link/Customer:120",			
		_("Total") + ":Currency:120",
		_("Paid") + ":Currency:100",
		_("Outstanding") + ":Currency:100"		
	]
