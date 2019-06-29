# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe, erpnext
import frappe.defaults
from frappe.utils import cint, flt
from frappe import _, msgprint, throw
from erpnext.accounts.party import get_party_account, get_due_date
from erpnext.controllers.stock_controller import update_gl_entries_after
from frappe.model.mapper import get_mapped_doc
from erpnext.accounts.doctype.sales_invoice.pos import update_multi_mode_option

from erpnext.controllers.selling_controller import SellingController
from erpnext.accounts.utils import get_account_currency
from erpnext.stock.doctype.delivery_note.delivery_note import update_billed_amount_based_on_so
from erpnext.projects.doctype.timesheet.timesheet import get_projectwise_timesheet_data
from erpnext.assets.doctype.asset.depreciation \
	import get_disposal_account_and_cost_center, get_gl_entries_on_asset_disposal
from erpnext.stock.doctype.batch.batch import set_batch_nos
from erpnext.stock.doctype.serial_no.serial_no import get_serial_nos, get_delivery_note_serial_no
from erpnext.setup.doctype.company.company import update_company_current_month_sales
from erpnext.accounts.general_ledger import get_round_off_account_and_cost_center

form_grid_templates = {
	"items": "templates/form_grid/item_grid.html"
}

class SalesInvoice(SellingController):
	def __init__(self, *args, **kwargs):
		super(SalesInvoice, self).__init__(*args, **kwargs)
		self.status_updater = [{
			'source_dt': 'Sales Invoice Item',
			'target_field': 'billed_amt',
			'target_ref_field': 'amount',
			'target_dt': 'Sales Order Item',
			'join_field': 'so_detail',
			'target_parent_dt': 'Sales Order',
			'target_parent_field': 'per_billed',
			'source_field': 'amount',
			'join_field': 'so_detail',
			'percent_join_field': 'sales_order',
			'status_field': 'billing_status',
			'keyword': 'Billed',
			'overflow_type': 'billing'
		}]

	def set_indicator(self):
		"""Set indicator for portal"""
		if self.outstanding_amount > 0:
			self.indicator_color = "orange"
			self.indicator_title = _("Unpaid")
		else:
			self.indicator_color = "green"
			self.indicator_title = _("Paid")

	def validate(self):
		super(SalesInvoice, self).validate()
		self.validate_auto_set_posting_time()

		if not self.is_pos:
			self.so_dn_required()

		self.set_missing_so_detail()
		self.validate_date()

		self.validate_proj_cust()
		self.validate_with_previous_doc()
		self.validate_uom_is_integer("stock_uom", "stock_qty")
		self.validate_uom_is_integer("uom", "qty")
		self.check_close_sales_order("sales_order")
		self.validate_debit_to_acc()
		self.clear_unallocated_advances("Sales Invoice Advance", "advances")
		self.add_remarks()
		self.validate_write_off_account()
		self.validate_account_for_change_amount()
		self.validate_fixed_asset()
		self.set_income_account_for_fixed_assets()

		if cint(self.is_pos):
			self.validate_pos()

		if cint(self.update_stock):
			self.validate_dropship_item()
			self.validate_item_code()
			self.validate_warehouse()
			self.update_current_stock()
			self.validate_delivery_note()

		if not self.is_opening:
			self.is_opening = 'No'

		if self._action != 'submit' and self.update_stock and not self.is_return:
			set_batch_nos(self, 'warehouse', True)


		self.set_against_income_account()
		self.validate_c_form()
		self.validate_time_sheets_are_submitted()
		self.validate_multiple_billing("Delivery Note", "dn_detail", "amount", "items")
		if not self.is_return:
			self.validate_serial_numbers()
		self.update_packing_list()
		self.set_billing_hours_and_amount()
		self.update_timesheet_billing_for_project()
		self.set_status()
		if self.is_pos and not self.is_return:
			self.verify_payment_amount_is_positive()

	def before_save(self):
		set_account_for_mode_of_payment(self)

	def on_submit(self):
		if not self.is_return:
			self.validate_taxes_and_charges_from_so()
		if self.update_stock:
			self.validate_user_warehouse()

		self.validate_pos_paid_amount()

		if not self.subscription:
			frappe.get_doc('Authorization Control').validate_approving_authority(self.doctype,
				self.company, self.base_grand_total, self)

		self.check_prev_docstatus()

		if self.is_return and not self.update_billed_amount_in_sales_order:
			# NOTE status updating bypassed for is_return
			self.status_updater = []

		self.update_status_updater_args()
		self.update_prevdoc_status()
		self.update_billing_status_in_dn()
		self.clear_unallocated_mode_of_payments()

		# Updating stock ledger should always be called after updating prevdoc status,
		# because updating reserved qty in bin depends upon updated delivered qty in SO
		if self.update_stock == 1:
			self.update_stock_ledger()
		else:
			self.update_reserved_qty()

		# this sequence because outstanding may get -ve
		self.make_gl_entries()

		if not self.is_return:
			self.update_billing_status_for_zero_amount_refdoc("Sales Order")
			self.check_credit_limit()

		self.update_serial_no()

		if not cint(self.is_pos) == 1 and not self.is_return:
			self.update_against_document_in_jv()

		self.update_time_sheet(self.name)

		update_company_current_month_sales(self.company)
		self.update_project()

	def validate_pos_paid_amount(self):
		if len(self.payments) == 0 and self.is_pos:
			frappe.throw(_("At least one mode of payment is required for POS invoice."))

	def before_cancel(self):
		self.update_time_sheet(None)

	def on_cancel(self):
		self.check_close_sales_order("sales_order")

		from erpnext.accounts.utils import unlink_ref_doc_from_payment_entries
		if frappe.db.get_single_value('Accounts Settings', 'unlink_payment_on_cancellation_of_invoice'):
			unlink_ref_doc_from_payment_entries(self)

		if self.is_return and not self.update_billed_amount_in_sales_order:
			# NOTE status updating bypassed for is_return
			self.status_updater = []

		self.update_status_updater_args()
		self.update_prevdoc_status()
		self.update_billing_status_in_dn()

		if not self.is_return:
			self.update_billing_status_for_zero_amount_refdoc("Sales Order")
			self.update_serial_no(in_cancel=True)

		self.validate_c_form_on_cancel()

		# Updating stock ledger should always be called after updating prevdoc status,
		# because updating reserved qty in bin depends upon updated delivered qty in SO
		if self.update_stock == 1:
			self.update_stock_ledger()
		else:
			self.update_reserved_qty()

		self.make_gl_entries_on_cancel()
		frappe.db.set(self, 'status', 'Cancelled')

		update_company_current_month_sales(self.company)
		self.update_project()

	def update_status_updater_args(self):
		if cint(self.update_stock):
			self.status_updater.extend([{
				'source_dt':'Sales Invoice Item',
				'target_dt':'Sales Order Item',
				'target_parent_dt':'Sales Order',
				'target_parent_field':'per_delivered',
				'target_field':'delivered_qty',
				'target_ref_field':'qty',
				'source_field':'qty',
				'join_field':'so_detail',
				'percent_join_field':'sales_order',
				'status_field':'delivery_status',
				'keyword':'Delivered',
				'second_source_dt': 'Delivery Note Item',
				'second_source_field': 'qty',
				'second_join_field': 'so_detail',
				'overflow_type': 'delivery',
				'extra_cond': """ and exists(select name from `tabSales Invoice`
					where name=`tabSales Invoice Item`.parent and update_stock = 1)"""
			},
			{
				'source_dt': 'Sales Invoice Item',
				'target_dt': 'Sales Order Item',
				'join_field': 'so_detail',
				'target_field': 'returned_qty',
				'target_parent_dt': 'Sales Order',
				# 'target_parent_field': 'per_delivered',
				# 'target_ref_field': 'qty',
				'source_field': '-1 * qty',
				# 'percent_join_field': 'sales_order',
				# 'overflow_type': 'delivery',
				'extra_cond': """ and exists (select name from `tabSales Invoice` where name=`tabSales Invoice Item`.parent and update_stock=1 and is_return=1)"""
			}
		])

	def check_credit_limit(self):
		from erpnext.selling.doctype.customer.customer import check_credit_limit

		validate_against_credit_limit = False
		bypass_credit_limit_check_at_sales_order = cint(frappe.db.get_value("Customer", self.customer,
			"bypass_credit_limit_check_at_sales_order"))
		if bypass_credit_limit_check_at_sales_order:
			validate_against_credit_limit = True

		for d in self.get("items"):
			if not (d.sales_order or d.delivery_note):
				validate_against_credit_limit = True
				break
		if validate_against_credit_limit:
			check_credit_limit(self.customer, self.company, bypass_credit_limit_check_at_sales_order)

	def set_missing_values(self, for_validate=False):
		pos = self.set_pos_fields(for_validate)

		if not self.debit_to:
			self.debit_to = get_party_account("Customer", self.customer, self.company)
		if not self.due_date and self.customer:
			self.due_date = get_due_date(self.posting_date, "Customer", self.customer, self.company)

		super(SalesInvoice, self).set_missing_values(for_validate)

		if pos:
			return {
				"print_format": pos.get("print_format_for_online"),
				"allow_edit_rate": pos.get("allow_user_to_edit_rate"),
				"allow_edit_discount": pos.get("allow_user_to_edit_discount")
			}

	def update_time_sheet(self, sales_invoice):
		for d in self.timesheets:
			if d.time_sheet:
				timesheet = frappe.get_doc("Timesheet", d.time_sheet)
				self.update_time_sheet_detail(timesheet, d, sales_invoice)
				timesheet.calculate_total_amounts()
				timesheet.calculate_percentage_billed()
				timesheet.flags.ignore_validate_update_after_submit = True
				timesheet.set_status()
				timesheet.save()

	def update_time_sheet_detail(self, timesheet, args, sales_invoice):
		for data in timesheet.time_logs:
			if (self.project and args.timesheet_detail == data.name) or \
				(not self.project and not data.sales_invoice) or \
				(not sales_invoice and data.sales_invoice == self.name):
				data.sales_invoice = sales_invoice

	def on_update(self):
		self.set_paid_amount()

	def set_paid_amount(self):
		paid_amount = 0.0
		base_paid_amount = 0.0
		for data in self.payments:
			data.base_amount = flt(data.amount*self.conversion_rate, self.precision("base_paid_amount"))
			paid_amount += data.amount
			base_paid_amount += data.base_amount

		self.paid_amount = paid_amount
		self.base_paid_amount = base_paid_amount

	def validate_time_sheets_are_submitted(self):
		for data in self.timesheets:
			if data.time_sheet:
				status = frappe.db.get_value("Timesheet", data.time_sheet, "status")
				if status not in ['Submitted', 'Payslip']:
					frappe.throw(_("Timesheet {0} is already completed or cancelled").format(data.time_sheet))

	def set_pos_fields(self, for_validate=False):
		"""Set retail related fields from POS Profiles"""
		if cint(self.is_pos) != 1:
			return

		from erpnext.stock.get_item_details import get_pos_profile_item_details, get_pos_profile
		if not self.pos_profile:
			pos_profile = get_pos_profile(self.company) or {}
			self.pos_profile = pos_profile.get('name')

		pos = {}
		if self.pos_profile:
			pos = frappe.get_doc('POS Profile', self.pos_profile)

		if not self.get('payments') and not for_validate:
			update_multi_mode_option(self, pos)

		if not self.account_for_change_amount:
			self.account_for_change_amount = frappe.db.get_value('Company', self.company, 'default_cash_account')

		if pos:
			if not for_validate and not self.customer:
				self.customer = pos.customer

			self.ignore_pricing_rule = pos.ignore_pricing_rule
			if pos.get('account_for_change_amount'):
				self.account_for_change_amount = pos.get('account_for_change_amount')

			for fieldname in ('territory', 'naming_series', 'currency', 'taxes_and_charges', 'letter_head', 'tc_name',
				'selling_price_list', 'company', 'select_print_heading', 'cash_bank_account',
				'write_off_account', 'write_off_cost_center', 'apply_discount_on'):
					if (not for_validate) or (for_validate and not self.get(fieldname)):
						self.set(fieldname, pos.get(fieldname))

			if not for_validate:
				self.update_stock = cint(pos.get("update_stock"))

			# set pos values in items
			for item in self.get("items"):
				if item.get('item_code'):
					for fname, val in get_pos_profile_item_details(pos,
						frappe._dict(item.as_dict()), pos, True).items():

						if (not for_validate) or (for_validate and not item.get(fname)):
							item.set(fname, val)

			# fetch terms
			if self.tc_name and not self.terms:
				self.terms = frappe.db.get_value("Terms and Conditions", self.tc_name, "terms")

			# fetch charges
			if self.taxes_and_charges and not len(self.get("taxes")):
				self.set_taxes()

		return pos

	def get_company_abbr(self):
		return frappe.db.sql("select abbr from tabCompany where name=%s", self.company)[0][0]

	def validate_debit_to_acc(self):
		account = frappe.db.get_value("Account", self.debit_to,
			["account_type", "report_type", "account_currency"], as_dict=True)

		if not account:
			frappe.throw(_("Debit To is required"))

		if account.report_type != "Balance Sheet":
			frappe.throw(_("Debit To account must be a Balance Sheet account"))

		if self.customer and account.account_type != "Receivable":
			frappe.throw(_("Debit To account must be a Receivable account"))

		self.party_account_currency = account.account_currency

	def clear_unallocated_mode_of_payments(self):
		self.set("payments", self.get("payments", {"amount": ["not in", [0, None, ""]]}))

		frappe.db.sql("""delete from `tabSales Invoice Payment` where parent = %s
			and amount = 0""", self.name)

	def validate_with_previous_doc(self):
		super(SalesInvoice, self).validate_with_previous_doc({
			"Sales Order": {
				"ref_dn_field": "sales_order",
				"compare_fields": [["customer", "="], ["company", "="], ["project", "="], ["currency", "="]]
			},
			"Sales Order Item": {
				"ref_dn_field": "so_detail",
				"compare_fields": [["item_code", "="], ["uom", "="], ["conversion_factor", "="]],
				"is_child_table": True,
				"allow_duplicate_prev_row_id": True
			},
			"Delivery Note": {
				"ref_dn_field": "delivery_note",
				"compare_fields": [["customer", "="], ["company", "="], ["project", "="], ["currency", "="]]
			},
			"Delivery Note Item": {
				"ref_dn_field": "dn_detail",
				"compare_fields": [["item_code", "="], ["uom", "="], ["conversion_factor", "="]],
				"is_child_table": True,
				"allow_duplicate_prev_row_id": True
			},
		})

		if cint(frappe.db.get_single_value('Selling Settings', 'maintain_same_sales_rate')) and not self.is_return:
			self.validate_rate_with_reference_doc([
				["Sales Order", "sales_order", "so_detail"],
				["Delivery Note", "delivery_note", "dn_detail"]
			])

	def set_against_income_account(self):
		"""Set against account for debit to account"""
		against_acc = []
		for d in self.get('items'):
			if d.income_account not in against_acc:
				against_acc.append(d.income_account)
		self.against_income_account = ','.join(against_acc)

	def add_remarks(self):
		if not self.remarks: self.remarks = 'No Remarks'

	def validate_auto_set_posting_time(self):
		# Don't auto set the posting date and time if invoice is amended
		if self.is_new() and self.amended_from:
			self.set_posting_time = 1

		self.validate_posting_time()

	def so_dn_required(self):
		"""check in manage account if sales order / delivery note required or not."""
		dic = {'Sales Order':['so_required', 'is_pos'],'Delivery Note':['dn_required', 'update_stock']}
		for i in dic:
			if frappe.db.get_value('Selling Settings', None, dic[i][0]) == 'Yes':
				for d in self.get('items'):
					if frappe.db.get_value('Item', d.item_code, 'is_stock_item') == 1 \
						and not d.get(i.lower().replace(' ','_')) and not self.get(dic[i][1]):
						msgprint(_("{0} is mandatory for Item {1}").format(i,d.item_code), raise_exception=1)


	def validate_proj_cust(self):
		"""check for does customer belong to same project as entered.."""
		if self.project and self.customer:
			res = frappe.db.sql("""select name from `tabProject`
				where name = %s and (customer = %s or customer is null or customer = '')""",
				(self.project, self.customer))
			if not res:
				throw(_("Customer {0} does not belong to project {1}").format(self.customer,self.project))

	def validate_pos(self):
		if self.is_return:
			if flt(self.paid_amount) + flt(self.write_off_amount) - flt(self.grand_total) < \
				1/(10**(self.precision("grand_total") + 1)):
					frappe.throw(_("Paid amount + Write Off Amount can not be greater than Grand Total"))

	def validate_item_code(self):
		for d in self.get('items'):
			if not d.item_code:
				msgprint(_("Item Code required at Row No {0}").format(d.idx), raise_exception=True)

	def validate_warehouse(self):
		super(SalesInvoice, self).validate_warehouse()

		for d in self.get_item_list():
			if not d.warehouse and frappe.db.get_value("Item", d.item_code, "is_stock_item"):
				frappe.throw(_("Warehouse required for stock Item {0}").format(d.item_code))

	def validate_delivery_note(self):
		for d in self.get("items"):
			if d.delivery_note:
				msgprint(_("Stock cannot be updated against Delivery Note {0}").format(d.delivery_note), raise_exception=1)

	def validate_write_off_account(self):
		if flt(self.write_off_amount) and not self.write_off_account:
			self.write_off_account = frappe.db.get_value('Company', self.company, 'write_off_account')

		if flt(self.write_off_amount) and not self.write_off_account:
			msgprint(_("Please enter Write Off Account"), raise_exception=1)

	def validate_account_for_change_amount(self):
		if flt(self.change_amount) and not self.account_for_change_amount:
			msgprint(_("Please enter Account for Change Amount"), raise_exception=1)

	def validate_c_form(self):
		""" Blank C-form no if C-form applicable marked as 'No'"""
		if self.amended_from and self.c_form_applicable == 'No' and self.c_form_no:
			frappe.db.sql("""delete from `tabC-Form Invoice Detail` where invoice_no = %s
					and parent = %s""", (self.amended_from,	self.c_form_no))

			frappe.db.set(self, 'c_form_no', '')

	def validate_c_form_on_cancel(self):
		""" Display message if C-Form no exists on cancellation of Sales Invoice"""
		if self.c_form_applicable == 'Yes' and self.c_form_no:
			msgprint(_("Please remove this Invoice {0} from C-Form {1}")
				.format(self.name, self.c_form_no), raise_exception = 1)

	def validate_dropship_item(self):
		for item in self.items:
			if item.sales_order:
				if frappe.db.get_value("Sales Order Item", item.so_detail, "delivered_by_supplier"):
					frappe.throw(_("Could not update stock, invoice contains drop shipping item."))

	def update_current_stock(self):
		for d in self.get('items'):
			if d.item_code and d.warehouse:
				bin = frappe.db.sql("select actual_qty from `tabBin` where item_code = %s and warehouse = %s", (d.item_code, d.warehouse), as_dict = 1)
				d.actual_qty = bin and flt(bin[0]['actual_qty']) or 0

		for d in self.get('packed_items'):
			bin = frappe.db.sql("select actual_qty, projected_qty from `tabBin` where item_code =	%s and warehouse = %s", (d.item_code, d.warehouse), as_dict = 1)
			d.actual_qty = bin and flt(bin[0]['actual_qty']) or 0
			d.projected_qty = bin and flt(bin[0]['projected_qty']) or 0

	def update_packing_list(self):
		if cint(self.update_stock) == 1:
			from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
			make_packing_list(self)
		else:
			self.set('packed_items', [])

	def set_billing_hours_and_amount(self):
		if not self.project:
			for timesheet in self.timesheets:
				ts_doc = frappe.get_doc('Timesheet', timesheet.time_sheet)
				if not timesheet.billing_hours and ts_doc.total_billable_hours:
					timesheet.billing_hours = ts_doc.total_billable_hours

				if not timesheet.billing_amount and ts_doc.total_billable_amount:
					timesheet.billing_amount = ts_doc.total_billable_amount

	def update_timesheet_billing_for_project(self):
		if not self.timesheets and self.project:
			self.add_timesheet_data()
		else:
			self.calculate_billing_amount_for_timesheet()

	def add_timesheet_data(self):
		self.set('timesheets', [])
		if self.project:
			for data in get_projectwise_timesheet_data(self.project):
				self.append('timesheets', {
						'time_sheet': data.parent,
						'billing_hours': data.billing_hours,
						'billing_amount': data.billing_amt,
						'timesheet_detail': data.name
					})

			self.calculate_billing_amount_for_timesheet()

	def calculate_billing_amount_for_timesheet(self):
		total_billing_amount = 0.0
		for data in self.timesheets:
			if data.billing_amount:
				total_billing_amount += data.billing_amount

		self.total_billing_amount = total_billing_amount

	def get_warehouse(self):
		user_pos_profile = frappe.db.sql("""select name, warehouse from `tabPOS Profile`
			where ifnull(user,'') = %s and company = %s""", (frappe.session['user'], self.company))
		warehouse = user_pos_profile[0][1] if user_pos_profile else None

		if not warehouse:
			global_pos_profile = frappe.db.sql("""select name, warehouse from `tabPOS Profile`
				where (user is null or user = '') and company = %s""", self.company)

			if global_pos_profile:
				warehouse = global_pos_profile[0][1]
			elif not user_pos_profile:
				msgprint(_("POS Profile required to make POS Entry"), raise_exception=True)

		return warehouse

	def set_income_account_for_fixed_assets(self):
		disposal_account = depreciation_cost_center = None
		for d in self.get("items"):
			if d.is_fixed_asset:
				if not disposal_account:
					disposal_account, depreciation_cost_center = get_disposal_account_and_cost_center(self.company)

				d.income_account = disposal_account
				if not d.cost_center:
					d.cost_center = depreciation_cost_center

	def check_prev_docstatus(self):
		for d in self.get('items'):
			if d.sales_order and frappe.db.get_value("Sales Order", d.sales_order, "docstatus") != 1:
				frappe.throw(_("Sales Order {0} is not submitted").format(d.sales_order))

			if d.delivery_note and frappe.db.get_value("Delivery Note", d.delivery_note, "docstatus") != 1:
				throw(_("Delivery Note {0} is not submitted").format(d.delivery_note))

	def make_gl_entries(self, gl_entries=None, repost_future_gle=True, from_repost=False):
		auto_accounting_for_stock = erpnext.is_perpetual_inventory_enabled(self.company)

		if not self.grand_total:
			return

		if not gl_entries:
			gl_entries = self.get_gl_entries()

		if gl_entries:
			from erpnext.accounts.general_ledger import make_gl_entries

			# if POS and amount is written off, updating outstanding amt after posting all gl entries
			update_outstanding = "No" if (cint(self.is_pos) or self.write_off_account) else "Yes"

			make_gl_entries(gl_entries, cancel=(self.docstatus == 2),
				update_outstanding=update_outstanding, merge_entries=False)

			if update_outstanding == "No":
				from erpnext.accounts.doctype.gl_entry.gl_entry import update_outstanding_amt
				update_outstanding_amt(self.debit_to, "Customer", self.customer,
					self.doctype, self.return_against if cint(self.is_return) else self.name)

			if repost_future_gle and cint(self.update_stock) \
				and cint(auto_accounting_for_stock):
					items, warehouses = self.get_items_and_warehouses()
					update_gl_entries_after(self.posting_date, self.posting_time, warehouses, items)
		elif self.docstatus == 2 and cint(self.update_stock) \
			and cint(auto_accounting_for_stock):
				from erpnext.accounts.general_ledger import delete_gl_entries
				delete_gl_entries(voucher_type=self.doctype, voucher_no=self.name)

	def get_gl_entries(self, warehouse_account=None):
		from erpnext.accounts.general_ledger import merge_similar_entries

		gl_entries = []

		self.make_customer_gl_entry(gl_entries)

		self.make_tax_gl_entries(gl_entries)

		self.make_item_gl_entries(gl_entries)

		# merge gl entries before adding pos entries
		gl_entries = merge_similar_entries(gl_entries)

		self.make_pos_gl_entries(gl_entries)
		self.make_gle_for_change_amount(gl_entries)

		self.make_write_off_gl_entry(gl_entries)
		self.make_gle_for_rounding_adjustment(gl_entries)

		return gl_entries

	def make_customer_gl_entry(self, gl_entries):
		grand_total = self.rounded_total or self.grand_total
		if grand_total:
			# Didnot use base_grand_total to book rounding loss gle
			grand_total_in_company_currency = flt(grand_total * self.conversion_rate,
				self.precision("grand_total"))

			gl_entries.append(
				self.get_gl_dict({
					"account": self.debit_to,
					"party_type": "Customer",
					"party": self.customer,
					"against": self.against_income_account,
					"debit": grand_total_in_company_currency,
					"debit_in_account_currency": grand_total_in_company_currency \
						if self.party_account_currency==self.company_currency else grand_total,
					"against_voucher": self.return_against if cint(self.is_return) else self.name,
					"against_voucher_type": self.doctype
				}, self.party_account_currency)
			)

	def make_tax_gl_entries(self, gl_entries):
		for tax in self.get("taxes"):
			if flt(tax.base_tax_amount_after_discount_amount):
				account_currency = get_account_currency(tax.account_head)
				gl_entries.append(
					self.get_gl_dict({
						"account": tax.account_head,
						"against": self.customer,
						"credit": flt(tax.base_tax_amount_after_discount_amount),
						"credit_in_account_currency": flt(tax.base_tax_amount_after_discount_amount) \
							if account_currency==self.company_currency else flt(tax.tax_amount_after_discount_amount),
						"cost_center": tax.cost_center
					}, account_currency)
				)

	def make_item_gl_entries(self, gl_entries):
		# income account gl entries
		for item in self.get("items"):
			if flt(item.base_net_amount):
				if item.is_fixed_asset:
					asset = frappe.get_doc("Asset", item.asset)

					fixed_asset_gl_entries = get_gl_entries_on_asset_disposal(asset, item.base_net_amount)
					for gle in fixed_asset_gl_entries:
						gle["against"] = self.customer
						gl_entries.append(self.get_gl_dict(gle))

					asset.db_set("disposal_date", self.posting_date)
					asset.set_status("Sold" if self.docstatus==1 else None)
				else:
					account_currency = get_account_currency(item.income_account)
					gl_entries.append(
						self.get_gl_dict({
							"account": item.income_account,
							"against": self.customer,
							"credit": item.base_net_amount,
							"credit_in_account_currency": item.base_net_amount \
								if account_currency==self.company_currency else item.net_amount,
							"cost_center": item.cost_center
						}, account_currency)
					)

		# expense account gl entries
		if cint(self.update_stock) and \
			erpnext.is_perpetual_inventory_enabled(self.company):
			gl_entries += super(SalesInvoice, self).get_gl_entries()

	def make_pos_gl_entries(self, gl_entries):
		if cint(self.is_pos):
			for payment_mode in self.payments:
				if payment_mode.amount:
					# POS, make payment entries
					gl_entries.append(
						self.get_gl_dict({
							"account": self.debit_to,
							"party_type": "Customer",
							"party": self.customer,
							"against": payment_mode.account,
							"credit": payment_mode.base_amount,
							"credit_in_account_currency": payment_mode.base_amount \
								if self.party_account_currency==self.company_currency \
								else payment_mode.amount,
							"against_voucher": self.return_against if cint(self.is_return) else self.name,
							"against_voucher_type": self.doctype,
						}, self.party_account_currency)
					)

					payment_mode_account_currency = get_account_currency(payment_mode.account)
					gl_entries.append(
						self.get_gl_dict({
							"account": payment_mode.account,
							"against": self.customer,
							"debit": payment_mode.base_amount,
							"debit_in_account_currency": payment_mode.base_amount \
								if payment_mode_account_currency==self.company_currency \
								else payment_mode.amount
						}, payment_mode_account_currency)
					)

	def make_gle_for_change_amount(self, gl_entries):
		if cint(self.is_pos) and self.change_amount:
			if self.account_for_change_amount:
				gl_entries.append(
					self.get_gl_dict({
						"account": self.debit_to,
						"party_type": "Customer",
						"party": self.customer,
						"against": self.account_for_change_amount,
						"debit": flt(self.base_change_amount),
						"debit_in_account_currency": flt(self.base_change_amount) \
							if self.party_account_currency==self.company_currency else flt(self.change_amount),
						"against_voucher": self.return_against if cint(self.is_return) else self.name,
						"against_voucher_type": self.doctype
					}, self.party_account_currency)
				)

				gl_entries.append(
					self.get_gl_dict({
						"account": self.account_for_change_amount,
						"against": self.customer,
						"credit": self.base_change_amount
					})
				)
			else:
				frappe.throw(_("Select change amount account"), title="Mandatory Field")

	def make_write_off_gl_entry(self, gl_entries):
		# write off entries, applicable if only pos
		if self.write_off_account and self.write_off_amount:
			write_off_account_currency = get_account_currency(self.write_off_account)
			default_cost_center = frappe.db.get_value('Company', self.company, 'cost_center')

			gl_entries.append(
				self.get_gl_dict({
					"account": self.debit_to,
					"party_type": "Customer",
					"party": self.customer,
					"against": self.write_off_account,
					"credit": self.base_write_off_amount,
					"credit_in_account_currency": self.base_write_off_amount \
						if self.party_account_currency==self.company_currency else self.write_off_amount,
					"against_voucher": self.return_against if cint(self.is_return) else self.name,
					"against_voucher_type": self.doctype
				}, self.party_account_currency)
			)
			gl_entries.append(
				self.get_gl_dict({
					"account": self.write_off_account,
					"against": self.customer,
					"debit": self.base_write_off_amount,
					"debit_in_account_currency": self.base_write_off_amount \
						if write_off_account_currency==self.company_currency else self.write_off_amount,
					"cost_center": self.write_off_cost_center or default_cost_center
				}, write_off_account_currency)
			)

	def make_gle_for_rounding_adjustment(self, gl_entries):
		if self.rounding_adjustment:
			round_off_account, round_off_cost_center = \
				get_round_off_account_and_cost_center(self.company)

			gl_entries.append(
				self.get_gl_dict({
					"account": round_off_account,
					"against": self.customer,
					"credit_in_account_currency": self.rounding_adjustment,
					"credit": self.base_rounding_adjustment,
					"cost_center": round_off_cost_center,
				}
			))

	def update_billing_status_in_dn(self, update_modified=True):
		updated_delivery_notes = []
		for d in self.get("items"):
			if d.dn_detail:
				billed_amt = frappe.db.sql("""select sum(amount) from `tabSales Invoice Item`
					where dn_detail=%s and docstatus=1""", d.dn_detail)
				billed_amt = billed_amt and billed_amt[0][0] or 0
				frappe.db.set_value("Delivery Note Item", d.dn_detail, "billed_amt", billed_amt, update_modified=update_modified)
				updated_delivery_notes.append(d.delivery_note)
			elif d.so_detail:
				updated_delivery_notes += update_billed_amount_based_on_so(d.so_detail, update_modified)

		for dn in set(updated_delivery_notes):
			frappe.get_doc("Delivery Note", dn).update_billing_percentage(update_modified=update_modified)

	def on_recurring(self, reference_doc, subscription_doc):
		for fieldname in ("c_form_applicable", "c_form_no", "write_off_amount"):
			self.set(fieldname, reference_doc.get(fieldname))

		self.due_date = None

	def update_serial_no(self, in_cancel=False):
		""" update Sales Invoice refrence in Serial No """
		invoice = None if (in_cancel or self.is_return) else self.name
		if in_cancel and self.is_return:
			invoice = self.return_against

		for item in self.items:
			if not item.serial_no:
				continue

			for serial_no in item.serial_no.split("\n"):
				if serial_no and frappe.db.exists('Serial No', serial_no):
					sno = frappe.get_doc('Serial No', serial_no)
					sno.sales_invoice = invoice
					sno.db_update()

	def validate_serial_numbers(self):
		"""
			validate serial number agains Delivery Note and Sales Invoice
		"""
		self.set_serial_no_against_delivery_note()
		self.validate_serial_against_delivery_note()
		self.validate_serial_against_sales_invoice()

	def set_serial_no_against_delivery_note(self):
		for item in self.items:
			if item.serial_no and item.delivery_note and \
				item.qty != len(get_serial_nos(item.serial_no)):
				item.serial_no = get_delivery_note_serial_no(item.item_code, item.qty, item.delivery_note)

	def validate_serial_against_delivery_note(self):
		"""
			validate if the serial numbers in Sales Invoice Items are same as in
			Delivery Note Item
		"""

		for item in self.items:
			if not item.delivery_note or not item.dn_detail:
				continue

			serial_nos = frappe.db.get_value("Delivery Note Item", item.dn_detail, "serial_no") or ""
			dn_serial_nos = set(get_serial_nos(serial_nos))

			serial_nos = item.serial_no or ""
			si_serial_nos = set(get_serial_nos(serial_nos))

			if si_serial_nos - dn_serial_nos:
				frappe.throw(_("Serial Numbers in row {0} does not match with Delivery Note".format(item.idx)))

			if item.serial_no and cint(item.qty) != len(si_serial_nos):
				frappe.throw(_("Row {0}: {1} Serial numbers required for Item {2}. You have provided {3}.".format(
					item.idx, item.qty, item.item_code, len(si_serial_nos))))

	def validate_serial_against_sales_invoice(self):
		""" check if serial number is already used in other sales invoice """
		for item in self.items:
			if not item.serial_no:
				continue

			for serial_no in item.serial_no.split("\n"):
				sales_invoice = frappe.db.get_value("Serial No", serial_no, "sales_invoice")
				if sales_invoice and self.name != sales_invoice:
					frappe.throw(_("Serial Number: {0} is already referenced in Sales Invoice: {1}".format(
						serial_no, sales_invoice
					)))

	def update_project(self):
		if self.project:
			project = frappe.get_doc("Project", self.project)
			project.flags.dont_sync_tasks = True
			project.update_billed_amount()
			project.save()

	def verify_payment_amount_is_positive(self):
		for entry in self.payments:
			if entry.amount < 0:
				frappe.throw(_("Row #{0} (Payment Table): Amount must be positive").format(entry.idx))

	def set_missing_so_detail(self):
		for item in self.items:
			if item.sales_order and not item.so_detail:
				set_item_so_detail(item)

	def get_remaining_taxes_and_charges_amount(self, for_validate):
		sales_orders = set([d.sales_order for d in self.items])
		tax_balance = {}
		for so in sales_orders:
			order_taxes = frappe.db.sql("""
				select account_head, tax_amount
				from `tabSales Taxes and Charges`
				where parenttype='Sales Order' and parent=%s and charge_type='Actual'
			""", [so], as_dict=1)

			for tax in order_taxes:
				tax_balance.setdefault(tax.account_head, 0)
				tax_balance[tax.account_head] += tax.tax_amount

			docstatus_condition = "docstatus=1" if for_validate else "docstatus<2"
			invoice_taxes = frappe.db.sql("""
				select t.account_head, t.tax_amount
				from `tabSales Taxes and Charges` t
				where t.parenttype='Sales Invoice' and t.charge_type='Actual' and t.parent!=%s and exists(
					select i.parent from `tabSales Invoice Item` i where i.sales_order=%s and t.parent=i.parent
				) and {0}
			""".format(docstatus_condition), [self.name, so], as_dict=1)

			for tax in invoice_taxes:
				tax_balance.setdefault(tax.account_head, 0)
				tax_balance[tax.account_head] -= tax.tax_amount

		return tax_balance

	def validate_taxes_and_charges_from_so(self):
		if not self.taxes:
			return

		tax_balance = self.get_remaining_taxes_and_charges_amount(for_validate=True)
		for d in self.taxes:
			if d.charge_type == "Actual":
				if d.account_head not in tax_balance:
					frappe.throw(_("Row #{0}: {1} could not be found in Sales Order").format(d.idx, d.description))

				if d.tax_amount > tax_balance[d.account_head]:
					frappe.throw(_("Row #{0}: {1} can not be greater than remaining amount of {2}")
						.format(d.idx, d.description, tax_balance[d.account_head]))
	
	def validate_user_warehouse(self):
		user_warehouse = frappe.db.get_value("User",{"name": frappe.session['user']}, "user_warehouse")
		if self.is_return and not self.approval_receive_in_breakage :		
			for item in self.items:
				if not (item.warehouse in user_warehouse):
					frappe.throw(_("You are not allowed to submit Invoice in Warehoues:<b> {0} </b>  for Item Code  <b>{1}</b>")
					.format(item.warehouse,item.item_code))
		else:
			for item in self.items:
				if not (item.warehouse in user_warehouse or item.warehouse in (user_warehouse.replace("Normal","Breakage")) or item.warehouse in (user_warehouse.replace("Depot","Breakage"))):
					frappe.throw(_("You are not allowed to submit Invoice in Warehoues:<b> {0} </b>  for Item Code  <b>{1}</b>")
					.format(item.warehouse,item.item_code))

		


def set_item_so_detail(item):
	so_detail = frappe.db.sql_list("""
						select name
						from `tabSales Order Item`
						where docstatus = 1 and parent = %s and item_code = %s 
					""", [item.sales_order, item.item_code])

	if not so_detail:
		frappe.throw(_("Row {0}: Item {1} can not be found in Sales Order {2}").format(
			item.idx, item.item_code, item.sales_order))

	item.so_detail = so_detail[-1]

def get_list_context(context=None):
	from erpnext.controllers.website_list_for_contact import get_list_context
	list_context = get_list_context(context)
	list_context.update({
		'show_sidebar': True,
		'show_search': True,
		'no_breadcrumbs': True,
		'title': _('Invoices'),
	})
	return list_context

@frappe.whitelist()
def get_bank_cash_account(mode_of_payment, company):
	account = frappe.db.get_value("Mode of Payment Account",
		{"parent": mode_of_payment, "company": company}, "default_account")
	if not account:
		frappe.throw(_("Please set default Cash or Bank account in Mode of Payment {0}")
			.format(mode_of_payment))
	return {
		"account": account
	}

@frappe.whitelist()
def make_delivery_note(source_name, target_doc=None):
	def set_missing_values(source, target):
		if (not source.allow_delivery and source.paid_amount+source.total_advance < source.rounded_total):
			frappe.throw(_('Not allowed to create the Delivery Note before Payment'))
		target.ignore_pricing_rule = 1
		target.run_method("set_missing_values")
		target.run_method("calculate_taxes_and_totals")

	def update_item(source_doc, target_doc, source_parent):
		target_doc.qty = flt(source_doc.qty) - flt(source_doc.delivered_qty)
		target_doc.stock_qty = target_doc.qty * flt(source_doc.conversion_factor)

		target_doc.base_amount = target_doc.qty * flt(source_doc.base_rate)
		target_doc.amount = target_doc.qty * flt(source_doc.rate)

	doclist = get_mapped_doc("Sales Invoice", source_name, 	{
		"Sales Invoice": {
			"doctype": "Delivery Note",
			"validation": {
				"docstatus": ["=", 1]
			}
		},
		"Sales Invoice Item": {
			"doctype": "Delivery Note Item",
			"field_map": {
				"name": "si_detail",
				"parent": "against_sales_invoice",
				"serial_no": "serial_no",
				"sales_order": "against_sales_order",
				"so_detail": "so_detail",
				"cost_center": "cost_center"
			},
			"postprocess": update_item,
			"condition": lambda doc: doc.delivered_by_supplier!=1
		},
		"Sales Taxes and Charges": {
			"doctype": "Sales Taxes and Charges",
			"add_if_empty": True
		},
		"Sales Team": {
			"doctype": "Sales Team",
			"field_map": {
				"incentives": "incentives"
			},
			"add_if_empty": True
		}
	}, target_doc, set_missing_values)

	return doclist

@frappe.whitelist()
def make_sales_return(source_name, target_doc=None):
	from erpnext.controllers.sales_and_purchase_return import make_return_doc
	return make_return_doc("Sales Invoice", source_name, target_doc)

def set_account_for_mode_of_payment(self):
	for data in self.payments:
		if not data.account:
			data.account = get_bank_cash_account(data.mode_of_payment, self.company).get("account")

@frappe.whitelist()
def split_invoice_between_warehouse(source_name):
	source_doc = frappe.get_doc("Sales Invoice", source_name)

	for d in source_doc.items:
		if not d.warehouse:
			frappe.throw(_("Row {0}: Warehouse not selected for Item {1}".format(d.idx, d.item_code)))

	warehouses = set(map(lambda d: d.warehouse, source_doc.items))
	if len(warehouses) <= 1:
		frappe.throw(_("You can only split invoice if there is more than 1 warehouse selected"))

	first_warehouse = source_doc.items[0].warehouse
	warehouses.remove(first_warehouse)

	doc_list = []
	for warehouse in warehouses:
		doc = frappe.copy_doc(source_doc, ignore_no_copy=1)
		doc.direct_delivery_from_warehouse = 1
		doc.custom_delivery_warehouse = warehouse
		doc.set("taxes", [])
		doc.set("payment_schedule", [])

		doc.set("items", [])
		items = [d for d in source_doc.items if d.warehouse == warehouse]
		for item in items:
			doc.append("items", item)

		doc.set("advances", [])
		doc.calculate_taxes_and_totals()
		doc.set_advances()
		doc.save()
		doc_list.append(doc.name)

	to_remove = [d for d in source_doc.items if d.warehouse != first_warehouse]
	[source_doc.remove(d) for d in to_remove]
	for i, d in enumerate(source_doc.items):
		d.idx = i + 1
	source_doc.direct_delivery_from_warehouse = 1
	source_doc.custom_delivery_warehouse = first_warehouse
	source_doc.set("advances", [])

	tax_balance = source_doc.get_remaining_taxes_and_charges_amount(for_validate=False)
	for d in source_doc.taxes:
		if d.account_head in tax_balance:
			d.tax_amount = tax_balance[d.account_head]

	source_doc.calculate_taxes_and_totals()
	source_doc.set_advances()
	source_doc.save()

	frappe.msgprint(_("Sales Invoices ({0}) created".format(", ".join(doc_list))))

@frappe.whitelist()
def update_item_qty_based_on_sales_order(items):
	from six import string_types
	import json
	if isinstance(items, string_types):
		items = json.loads(items)

	out = {}

	items_codes_visited = set()
	for item in items:
		item = frappe._dict(item)
		if item.qty > 0:
			if item.sales_order:
				row = {}
				if not item.so_detail:
					set_item_so_detail(item)
					row['so_detail'] = item.so_detail

				so_item = frappe.get_value("Sales Order Item", item.so_detail, ["qty", "rate"], as_dict=1)
				if not so_item:
					frappe.msgprint("Row {0}: Ignoring Item {1}. Could not find Sales Order Item in {2}".format(
						item.idx, item.item_code, item.sales_order))

				row['rate'] = so_item.rate

				if item.item_code in items_codes_visited:
					row['qty'] = 0
				else:
					invoiced_qty = frappe.db.sql("""
						select sum(item.qty)
						from `tabSales Invoice Item` item
						inner join `tabSales Invoice` si on si.name = item.parent
						where si.docstatus < 2 and si.is_return != 1 and item.so_detail = %s and item.parent != %s
					""", [item.so_detail, item.parent])
					invoiced_qty = invoiced_qty[0][0] if invoiced_qty else 0
					invoiced_qty = flt(invoiced_qty)

					remaining_qty = max(0, so_item.qty - invoiced_qty)
					if remaining_qty< flt(item.qty):
						row['qty'] = remaining_qty

				out[item.name] = row
				items_codes_visited.add(item.item_code)

	return out

@frappe.whitelist()
def make_stock_entry(source_name, target_doc=None):
	def update_item(source_doc, target_doc, source_parent):
		target_doc.qty = abs(flt(source_doc.qty))
		target_doc.boxes = abs(int(source_doc.boxes))
		target_doc.pieces = abs(int(source_doc.pieces))
		target_doc.sqm = abs(flt(source_doc.sqm))

	doc = get_mapped_doc("Sales Invoice", source_name, {
		"Sales Invoice": {
			"doctype": "Stock Entry",
			"validation": {
				"docstatus": ["=", 1]
			}
		},
		"Sales Invoice Item": {
			"doctype": "Stock Entry Detail",
			"field_map": {
				"stock_qty": "transfer_qty"
			},
			"postprocess": update_item
		}
	}, target_doc)

	return doc
