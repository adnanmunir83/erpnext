# -*- coding: utf-8 -*-
# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document
from frappe.desk.form.linked_with import get_linked_doctypes
from frappe.utils import flt
from collections import defaultdict


class SalesOrderSummary(Document):
	pass


@frappe.whitelist()
def get_related_documents(doctype, docname):
	document_details = defaultdict(list)
	si_list = []
	linked_doc_info = get_linked_doctypes(doctype)

	document_details[doctype].append(frappe.get_doc(doctype, docname).as_dict())

	# also consider the sales return
	for linked_doctype in ["Sales Order", "Material Request", "Stock Entry", "Delivery Note", "Sales Invoice", "Payment Entry"]:
		link = linked_doc_info.get(linked_doctype)
		filters = [[link.get('child_doctype', linked_doctype), link.get("fieldname"), '=', docname]]
		if link.get("doctype_fieldname"):
			filters.append([link.get('child_doctype'), link.get("doctype_fieldname"), "=", doctype])

		if linked_doctype == "Payment Entry":
			filters.append(["Payment Entry", "docstatus", "=", 1])

		names = frappe.get_all(linked_doctype, fields="name", filters=filters, distinct=1)

		for doc in names:
			doc_obj = frappe.get_doc(linked_doctype, doc.name)

			if linked_doctype == "Sales Invoice":
				si_list.append(doc_obj.name)
			if linked_doctype == "Sales Invoice" and doc_obj.is_return:
				document_details["Sales Return"].append(doc_obj.as_dict())
			else:
				document_details[linked_doctype].append(doc_obj.as_dict())

	for so in document_details["Sales Order"]:
		for d in so.get("items"):
			d.remaining_qty = flt(d.qty) - flt(d.delivered_qty) - flt(d.returned_qty)

	# include the Payment Entry against invoice
	if si_list:
		payment_entry = frappe.db.sql(
			'''select distinct parent as name from `tabPayment Entry Reference` where docstatus=1 and reference_name in (%s)''' %
			', '.join(['%s'] * len(si_list)), tuple(si_list), as_dict=1)
		for pe in payment_entry:
			if pe.name not in document_details["Payment Entry"]:
				pe_doc = frappe.get_doc("Payment Entry", pe.name).as_dict()
				document_details["Payment Entry"].append(pe_doc)

	return document_details

