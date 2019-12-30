# -*- coding: utf-8 -*-
# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document
from frappe import _, msgprint, throw

class IncentiveCategory(Document):
	
	def on_update(self):
		if self.name:
			frappe.db.sql("update tabItem set incentive_amount=%s where incentive_category=%s",(self.incentive_amount,self.incentive_category))
