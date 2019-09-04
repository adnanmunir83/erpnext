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
			 posting_date, name , customer, payment_terms_template , grand_total ,
			 (select ifnull(sum(payment_gl_entry.credit_in_account_currency - payment_gl_entry.debit_in_account_currency), 0)
			from `tabGL Entry` payment_gl_entry
			where 
			payment_gl_entry.against_voucher = ts.name	
			and payment_gl_entry.party =ts.customer	
			and payment_gl_entry.credit_in_account_currency - payment_gl_entry.debit_in_account_currency > 0) paid_amount , 
			(grand_total - (select ifnull(sum(payment_gl_entry.credit_in_account_currency - payment_gl_entry.debit_in_account_currency), 0)
			from `tabGL Entry` payment_gl_entry
			where 
			payment_gl_entry.against_voucher = ts.name	
			and payment_gl_entry.party =ts.customer	
			and payment_gl_entry.credit_in_account_currency - payment_gl_entry.debit_in_account_currency > 0) ) outstanding_amount
			, company

			from `tabSales Invoice` ts

			where 
			grand_total-1>(select ifnull(sum(payment_gl_entry.credit_in_account_currency - payment_gl_entry.debit_in_account_currency), 0)
			from `tabGL Entry` payment_gl_entry
			where 
			payment_gl_entry.against_voucher = ts.name	
			and payment_gl_entry.party =ts.customer	
			and payment_gl_entry.credit_in_account_currency - payment_gl_entry.debit_in_account_currency > 0) 
			
			and docstatus=1
			{0}
			and posting_date >= %(fdate)s
			and posting_date <= %(tdate)s
			order by customer""".format(customer_condition), filters, as_dict=False)

def get_columns():
	"""return columns"""

	columns = [
		_("Date")+":Date:100",
		_("Invoice No")+":Link/Sales Invoice:100",
		_("Customer")+":Link/Customer:200",
		_("Payment Terms")+":Data:100",
		_("Total")+":Float:100",	
		_("Paid")+":Float:100",
		_("Outstanding")+":Float:100",	
		_("Company")+":Link/Company:100"
	]

	return columns