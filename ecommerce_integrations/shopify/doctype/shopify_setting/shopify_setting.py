# Copyright (c) 2021, Frappe and contributors
# For license information, please see LICENSE

from typing import Dict, List

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import get_datetime
from shopify.collection import PaginatedIterator
from shopify.resources import Location

from ecommerce_integrations.controllers.setting import (
	ERPNextWarehouse,
	IntegrationWarehouse,
	SettingController,
)
from ecommerce_integrations.shopify import connection
from ecommerce_integrations.shopify.constants import (
	ADDRESS_ID_FIELD,
	BILLING_ADDRESS_DISPLAY_FIELD,
	BILLING_ADDRESS_FIELD,
	CUSTOMER_FULL_NAME_FIELD,
	CUSTOMER_ID_FIELD,
	EMAIL_FIELD,
	FULLFILLMENT_ID_FIELD,
	ITEM_SELLING_RATE_FIELD,
	ORDER_ID_FIELD,
	ORDER_ITEM_DISCOUNT_FIELD,
	ORDER_NUMBER_FIELD,
	ORDER_STATUS_FIELD,
	PHONE_NUMBER_FIELD,
	SHIPPING_ADDRESS_DISPLAY_FIELD,
	SHIPPING_ADDRESS_FIELD,
	SUPPLIER_ID_FIELD,
)
from ecommerce_integrations.shopify.utils import (
	ensure_old_connector_is_disabled,
	migrate_from_old_connector,
)


class ShopifySetting(SettingController):
	def is_enabled(self) -> bool:
		return bool(self.enable_shopify)

	def validate(self):
		ensure_old_connector_is_disabled()

		if self.shopify_url:
			self.shopify_url = self.shopify_url.replace("https://", "")
		self._handle_webhooks()
		self._validate_warehouse_links()
		self._initalize_default_values()

		if self.is_enabled():
			setup_custom_fields()

	def on_update(self):
		if self.is_enabled() and not self.is_old_data_migrated:
			migrate_from_old_connector()

	def _handle_webhooks(self):
		if self.is_enabled() and not self.webhooks:
			new_webhooks = connection.register_webhooks(self.shopify_url, self.get_password("password"))

			if not new_webhooks:
				msg = _("Failed to register webhooks with Shopify.") + "<br>"
				msg += _("Please check credentials and retry.") + " "
				msg += _("Disabling and re-enabling the integration might also help.")
				frappe.throw(msg)

			for webhook in new_webhooks:
				self.append("webhooks", {"webhook_id": webhook.id, "method": webhook.topic})

		elif not self.is_enabled():
			connection.unregister_webhooks(self.shopify_url, self.get_password("password"))

			self.webhooks = list()  # remove all webhooks

	def _validate_warehouse_links(self):
		for wh_map in self.shopify_warehouse_mapping:
			if not wh_map.erpnext_warehouse:
				frappe.throw(_("ERPNext warehouse required in warehouse map table."))

	def _initalize_default_values(self):
		if not self.last_inventory_sync:
			self.last_inventory_sync = get_datetime("1970-01-01")

	@frappe.whitelist()
	@connection.temp_shopify_session
	def update_location_table(self):
		"""Fetch locations from shopify and add it to child table so user can
		map it with correct ERPNext warehouse."""

		self.shopify_warehouse_mapping = []
		for locations in PaginatedIterator(Location.find()):
			for location in locations:
				self.append(
					"shopify_warehouse_mapping",
					{"shopify_location_id": location.id, "shopify_location_name": location.name},
				)

	def get_erpnext_warehouses(self) -> List[ERPNextWarehouse]:
		return [wh_map.erpnext_warehouse for wh_map in self.shopify_warehouse_mapping]

	def get_erpnext_to_integration_wh_mapping(self) -> Dict[ERPNextWarehouse, IntegrationWarehouse]:
		wh_map = {wh_map.erpnext_warehouse: wh_map.shopify_location_id for wh_map in self.shopify_warehouse_mapping}
		child_warehouse_details = {warehouse: get_child_nodes("Warehouse", warehouse) for warehouse in wh_map.keys()}
		child_wh_mapping = {
			row: shopify_location_id
			for erpnext_wh, shopify_location_id in wh_map.items()
			for row in child_warehouse_details[erpnext_wh]
		}
		return child_wh_mapping

	def get_integration_to_erpnext_wh_mapping(self) -> Dict[IntegrationWarehouse, ERPNextWarehouse]:
		return {
			wh_map.shopify_location_id: wh_map.erpnext_warehouse
			for wh_map in self.shopify_warehouse_mapping
		}

def get_child_nodes(group_type, root):
	lft, rgt = frappe.db.get_value(group_type, root, ["lft", "rgt"])
	return frappe.get_all(group_type,{
		"is_group" : 0,
		"sync_inventory_to_shopify" : 1,
		"lft" : [">=", lft],
		"rgt" : ["<=", rgt]
	},pluck="name",order_by="lft")

def setup_custom_fields():
	custom_fields = {
		"Item": [
			dict(
				fieldname=ITEM_SELLING_RATE_FIELD,
				label="Shopify Selling Rate",
				fieldtype="Currency",
				insert_after="standard_rate",
			)
		],
		"Customer": [
			dict(
				fieldname=CUSTOMER_ID_FIELD,
				label="Shopify Customer Id",
				fieldtype="Data",
				insert_after="series",
				read_only=1,
				print_hide=1,
			)
		],
		"Supplier": [
			dict(
				fieldname=SUPPLIER_ID_FIELD,
				label="Shopify Supplier Id",
				fieldtype="Data",
				insert_after="supplier_name",
				read_only=1,
				print_hide=1,
			)
		],
		"Address": [
			dict(
				fieldname=ADDRESS_ID_FIELD,
				label="Shopify Address Id",
				fieldtype="Data",
				insert_after="fax",
				read_only=1,
				print_hide=1,
			)
		],
		"Sales Order": [
			dict(
				fieldname=ORDER_ID_FIELD,
				label="Shopify Order Id",
				fieldtype="Small Text",
				insert_after="title",
				read_only=1,
				print_hide=1,
			),
			dict(
				fieldname=ORDER_NUMBER_FIELD,
				label="Shopify Order Number",
				fieldtype="Small Text",
				insert_after=ORDER_ID_FIELD,
				read_only=1,
				print_hide=1,
			),
			dict(
				fieldname="tb_shopify_details",
				label="Shopify Details",
				fieldtype="Tab Break",
				insert_after="connections_tab",
			),
			dict(
				fieldname="sb_shopify_customer_details",
				label="Shopify Customer Details",
				fieldtype="Section Break",
				insert_after="tb_shopify_details",
			),
			dict(
				fieldname=CUSTOMER_ID_FIELD,
				label="Shopify Platform Customer",
				fieldtype="Link",
				options="Shopify Platform Customer",
				insert_after="sb_shopify_customer_details",
			),
			dict(
				fieldname=CUSTOMER_FULL_NAME_FIELD,
				label="Shopify Customer Full Name",
				fieldtype="Data",
				insert_after=CUSTOMER_ID_FIELD,
				fetch_from=f"{CUSTOMER_ID_FIELD}.full_name",
			),
			dict(
				fieldname="cb_shopify_customer_details",
				fieldtype="Column Break",
				insert_after=CUSTOMER_FULL_NAME_FIELD,
			),
			dict(
				fieldname=PHONE_NUMBER_FIELD,
				label="Shopify Customer Phone Number",
				fieldtype="Data",
				insert_after="cb_shopify_customer_details",
				fetch_from=f"{CUSTOMER_ID_FIELD}.phone",
			),
			dict(
				fieldname=EMAIL_FIELD,
				label="Shopify Customer Email",
				fieldtype="Data",
				insert_after=PHONE_NUMBER_FIELD,
				fetch_from=f"{CUSTOMER_ID_FIELD}.email",
			),
			dict(
				fieldname="sb_shopify_address",
				label="Shopify Address Details",
				fieldtype="Section Break",
				insert_after=EMAIL_FIELD,
			),
			dict(
				fieldname=BILLING_ADDRESS_FIELD,
				label="Billing Address",
				fieldtype="Link",
				options="Address",
				insert_after="sb_shopify_address",
			),
			dict(
				fieldname=BILLING_ADDRESS_DISPLAY_FIELD,
				label="Billing Address Display",
				fieldtype="Small Text",
				insert_after=BILLING_ADDRESS_FIELD,
			),
			dict(
				fieldname="cb_shopify_address",
				fieldtype="Column Break",
				insert_after=BILLING_ADDRESS_DISPLAY_FIELD,
			),
			dict(
				fieldname=SHIPPING_ADDRESS_FIELD,
				label="Shipping Address",
				fieldtype="Link",
				options="Address",
				insert_after="cb_shopify_address",
			),
			dict(
				fieldname=SHIPPING_ADDRESS_DISPLAY_FIELD,
				label="Shipping Address Display",
				fieldtype="Small Text",
				insert_after=SHIPPING_ADDRESS_FIELD,
			),
		],
		"Sales Order Item": [
			dict(
				fieldname=ORDER_ITEM_DISCOUNT_FIELD,
				label="Shopify Discount per unit",
				fieldtype="Float",
				insert_after="discount_and_margin",
				read_only=1,
			),
			dict(
				fieldname=ORDER_STATUS_FIELD,
				label="Shopify Order Status",
				fieldtype="Small Text",
				insert_after=ORDER_NUMBER_FIELD,
				read_only=1,
				print_hide=1,
			),
		],
		"Delivery Note": [
			dict(
				fieldname=ORDER_ID_FIELD,
				label="Shopify Order Id",
				fieldtype="Small Text",
				insert_after="title",
				read_only=1,
				print_hide=1,
			),
			dict(
				fieldname=ORDER_NUMBER_FIELD,
				label="Shopify Order Number",
				fieldtype="Small Text",
				insert_after=ORDER_ID_FIELD,
				read_only=1,
				print_hide=1,
			),
			dict(
				fieldname=ORDER_STATUS_FIELD,
				label="Shopify Order Status",
				fieldtype="Small Text",
				insert_after=ORDER_NUMBER_FIELD,
				read_only=1,
				print_hide=1,
			),
			dict(
				fieldname=FULLFILLMENT_ID_FIELD,
				label="Shopify Fulfillment Id",
				fieldtype="Small Text",
				insert_after="title",
				read_only=1,
				print_hide=1,
			),
		],
		"Sales Invoice": [
			dict(
				fieldname=ORDER_ID_FIELD,
				label="Shopify Order Id",
				fieldtype="Small Text",
				insert_after="title",
				read_only=1,
				print_hide=1,
			),
			dict(
				fieldname=ORDER_NUMBER_FIELD,
				label="Shopify Order Number",
				fieldtype="Small Text",
				insert_after=ORDER_ID_FIELD,
				read_only=1,
				print_hide=1,
			),
			dict(
				fieldname=ORDER_STATUS_FIELD,
				label="Shopify Order Status",
				fieldtype="Small Text",
				insert_after=ORDER_ID_FIELD,
				read_only=1,
				print_hide=1,
			),
		],
		"Warehouse": [
			dict(
				fieldname = "shopify_settings",
				label = "Shopify Settings",
				fieldtype = "Section Break",
				insert_after = "default_in_transit_warehouse",
			),
			dict(
				fieldname="sync_inventory_to_shopify",
				label="Sync Inventory to Shopify",
				fieldtype="Check",
				insert_after="shopify_settings",
			),
		]
	}

	create_custom_fields(custom_fields)
