from __future__ import unicode_literals
from frappe import _

def get_data():
	return [
		{
			"label": _("Assets"),
			"items": [
				{
					"type": "doctype",
					"name": "Asset",
				},
				{
					"type": "doctype",
					"name": "Location",
				},
				{
					"type": "doctype",
					"name": "Asset Category",
				},
				{
					"type": "doctype",
					"name": "Asset Settings",
				}
			]
		},
		{
			"label": _("Maintenance"),
			"items": [
				{
					"type": "doctype",
					"name": "Asset Maintenance Team",
				},
				{
					"type": "doctype",
					"name": "Asset Maintenance",
				},
				{
					"type": "doctype",
					"name": "Asset Maintenance Tasks",
				},
				{
					"type": "doctype",
					"name": "Asset Maintenance Log",
				},
				{
					"type": "doctype",
					"name": "Asset Adjustment",
				},
				{
					"type": "doctype",
					"name": "Asset Repair",
				},
			]
		},
		{
			"label": _("Tools"),
			"items": [
				{
					"type": "doctype",
					"name": "Asset Movement",
					"description": _("Transfer an asset from one warehouse to another")
				},
			]
		}
	]
