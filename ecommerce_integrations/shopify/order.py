import json
from typing import Literal, Optional

import frappe
from frappe import _
from frappe.contacts.doctype.address.address import get_address_display
from frappe.utils import cint, cstr, flt, get_datetime, getdate, nowdate
from shopify.collection import PaginatedIterator
from shopify.resources import Order

from ecommerce_integrations.shopify.connection import temp_shopify_session
from ecommerce_integrations.shopify.constants import (
	EVENT_MAPPER,
	ORDER_ID_FIELD,
	ORDER_ITEM_DISCOUNT_FIELD,
	ORDER_NUMBER_FIELD,
	ORDER_STATUS_FIELD,
	SETTING_DOCTYPE,
)
from ecommerce_integrations.shopify.customer import ShopifyCustomer
from ecommerce_integrations.shopify.product import create_items_if_not_exist, get_item_code
from ecommerce_integrations.shopify.utils import create_shopify_log
from ecommerce_integrations.utils.price_list import get_dummy_price_list
from ecommerce_integrations.utils.taxation import get_dummy_tax_category

DEFAULT_TAX_FIELDS = {
	"sales_tax": "default_sales_tax_account",
	"shipping": "default_shipping_charges_account",
}


def sync_sales_order(payload, request_id=None):
	order = payload
	frappe.set_user("Administrator")
	frappe.flags.request_id = request_id

	if frappe.db.get_value("Sales Order", filters={ORDER_ID_FIELD: cstr(order["id"])}):
		create_shopify_log(status="Invalid", message="Sales order already exists, not synced")
		return
	try:
		shopify_customer = order.get("customer") if order.get("customer") is not None else {}
		shopify_customer["billing_address"] = order.get("billing_address", "")
		shopify_customer["shipping_address"] = order.get("shipping_address", "")
		customer_id = shopify_customer.get("id")
		if customer_id:
			shopify_platform_customer = ShopifyCustomer(customer_id=customer_id)
			if not shopify_platform_customer.is_synced():
				shopify_platform_customer.sync_customer(customer=shopify_customer)
			else:
				shopify_platform_customer.update_existing_addresses(shopify_customer)

		create_items_if_not_exist(order)

		setting = frappe.get_doc(SETTING_DOCTYPE)
		create_order(order, setting)
	except Exception as e:
		create_shopify_log(status="Error", exception=e, rollback=True)
	else:
		create_shopify_log(status="Success")


def create_order(order, setting, company=None):
	# local import to avoid circular dependencies
	from ecommerce_integrations.shopify.fulfillment import create_delivery_note
	from ecommerce_integrations.shopify.invoice import create_sales_invoice

	so = create_sales_order(order, setting, company)
	if so:
		if order.get("financial_status") == "paid":
			create_sales_invoice(order, setting, so)

		if order.get("fulfillments"):
			create_delivery_note(order, setting, so)


def create_sales_order(shopify_order, setting, company=None):
	from ecommerce_integrations.shopify.customer import (
		get_shopify_platform_customer_address_doc as platform_customer_address_doc,
	)

	customer = setting.default_customer

	billing_address = None
	billing_address_display = None
	shipping_address = None
	shipping_address_display = None
	if shopify_order.get("customer", {}):
		if customer_id := shopify_order.get("customer", {}).get("id"):
			if billing_address := platform_customer_address_doc(customer_id, address_type="Billing"):
				billing_address_display = get_address_display(billing_address.as_dict())
			if shipping_address := platform_customer_address_doc(customer_id, address_type="Shipping"):
				shipping_address_display = get_address_display(shipping_address.as_dict())

	so = frappe.db.get_value("Sales Order", {ORDER_ID_FIELD: shopify_order.get("id")}, "name")
	# Create customer fullname
	# if shopify_order.get("customer"):
	# 	first_name = shopify_order.get("customer").get("first_name", "")
	# 	last_name = shopify_order.get("customer").get("last_name", "")
	# 	shopify_customer_full_name = first_name + " " + last_name
	# else:
	# 	shopify_customer_full_name = ""

	# Create billing address with below sample data
	# if shopify_order.get("billing_address"):
	# 	address_line_1 = shopify_order.get("billing_address").get("address1", "")
	# 	address_line_2 = shopify_order.get("billing_address").get("address2", "")
	# 	city = shopify_order.get("billing_address").get("city", "")
	# 	zip_code = shopify_order.get("billing_address").get("zip", "")
	# 	province = shopify_order.get("billing_address").get("province", "")
	# 	country = shopify_order.get("billing_address").get("country", "")
	# 	phone = shopify_order.get("billing_address").get("phone", "")
	# 	shopify_billing_address = address_line_1 + ",\n" + address_line_2 + ",\n" + city + ",\n" + zip_code + ",\n" + province + ",\n" + country + ",\n" + phone
	# else:
	# 	shopify_billing_address = ""
	# if shopify_order.get("billing_address"):
	# 	billing_address = shopify_order.get("billing_address")
	# 	address_line_1 = str(billing_address.get("address1", "") or "")
	# 	address_line_2 = str(billing_address.get("address2", "") or "")
	# 	city = str(billing_address.get("city", "") or "")
	# 	zip_code = str(billing_address.get("zip", "") or "")
	# 	province = str(billing_address.get("province", "") or "")
	# 	country = str(billing_address.get("country", "") or "")
	# 	phone = str(billing_address.get("phone", "") or "")

		# Join non-empty parts with a newline
		# shopify_billing_address = ",\n".join(
		# 	filter(None, [address_line_1, address_line_2, city, zip_code, province, country, phone])
		# )
	# else:
	# 	shopify_billing_address = ""

	# Create shipping address with below sample data
	# if shopify_order.get("shipping_address"):
	# 	address_line_1 = shopify_order.get("shipping_address").get("address1", "")
	# 	address_line_2 = shopify_order.get("shipping_address").get("address2", "")
	# 	city = shopify_order.get("shipping_address").get("city", "")
	# 	zip_code = shopify_order.get("shipping_address").get("zip", "")
	# 	province = shopify_order.get("shipping_address").get("province", "")
	# 	country = shopify_order.get("shipping_address").get("country", "")
	# 	phone = shopify_order.get("shipping_address").get("phone", "")
	# 	shopify_shipping_address = address_line_1 + ",\n" + address_line_2 + ",\n" + city + ",\n" + zip_code + ",\n" + province + ",\n" + country + ",\n" + phone
	# else:
	# 	shopify_shipping_address = ""
	# if shopify_order.get("shipping_address"):
	# 	shipping_address = shopify_order.get("shipping_address")
	# 	address_line_1 = shipping_address.get("address1", "") or ""
	# 	address_line_2 = shipping_address.get("address2", "") or ""
	# 	city = shipping_address.get("city", "") or ""
	# 	zip_code = shipping_address.get("zip", "") or ""
	# 	province = shipping_address.get("province", "") or ""
	# 	country = shipping_address.get("country", "") or ""
	# 	phone = shipping_address.get("phone", "") or ""

		# Construct the shipping address string
		# address_parts = [address_line_1, address_line_2, city, zip_code, province, country, phone]
		# address_parts = [part for part in address_parts if part]  # Remove empty or None values
		# shopify_shipping_address = ",\n".join(address_parts)
	# else:
	# 	shopify_shipping_address = ""

	if not so:
		items = get_order_items(
			shopify_order.get("line_items"),
			setting,
			getdate(shopify_order.get("created_at")),
			taxes_inclusive=shopify_order.get("taxes_included"),
		)

		if not items:
			message = (
				"Following items exists in the shopify order but relevant records were"
				" not found in the shopify Product master"
			)
			product_not_exists = []  # TODO: fix missing items
			message += "\n" + ", ".join(product_not_exists)

			create_shopify_log(status="Error", exception=message, rollback=True)

			return ""
		
		selling_price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")
		if not selling_price_list:	
			selling_price_list = get_dummy_price_list()
		
		taxes = get_order_taxes(shopify_order, setting, items)
		so = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"naming_series": setting.sales_order_series or "SO-Shopify-",
				ORDER_ID_FIELD: str(shopify_order.get("id")),
				ORDER_NUMBER_FIELD: shopify_order.get("name"),
				"customer": customer,
				# "custom_shopify_customer_name": shopify_customer_full_name,
				# "custom_shopify_customer_billing_address": billing_address_display,
				# "custom_shopify_customer_shipping_address": shipping_address_display,
				"transaction_date": getdate(shopify_order.get("created_at")) or nowdate(),
				"delivery_date": getdate(shopify_order.get("created_at")) or nowdate(),
				"company": setting.company,
				"selling_price_list": selling_price_list,
				"ignore_pricing_rule": 0,
				"items": items,
				"taxes": taxes,
				"tax_category": None,
				"shopify_customer_id": customer_id,
				"customer_address": billing_address.name if billing_address else None,
				"shopify_billing_address": billing_address.name if billing_address else None,
				"shopify_billing_address_display": billing_address_display,
				"shipping_address_name": shipping_address.name if shipping_address else None,
				"shopify_shipping_address": shipping_address.name if shipping_address else None,
				"shopify_shipping_address_display": shipping_address_display,
			}
		)

		if company:
			so.update({"company": company, "status": "Draft"})
		so.flags.ignore_mandatory = True
		so.flags.shopiy_order_json = json.dumps(shopify_order)
		so.run_method("calculate_taxes_and_totals")
		so.save(ignore_permissions=True)
		# so.submit()

		if shopify_order.get("note"):
			so.add_comment(text=f"Order Note: {shopify_order.get('note')}")

	else:
		so = frappe.get_doc("Sales Order", so)

	return so


def get_order_items(order_items, setting, delivery_date, taxes_inclusive):
	items = []
	all_product_exists = True
	product_not_exists = []

	for shopify_item in order_items:
		if not shopify_item.get("product_exists"):
			all_product_exists = False
			product_not_exists.append(
				{"title": shopify_item.get("title"), ORDER_ID_FIELD: shopify_item.get("id")}
			)
			continue

		if all_product_exists:
			item_code = get_item_code(shopify_item)
			items.append(
				{
					"item_code": item_code,
					"item_name": shopify_item.get("name"),
					"rate": _get_item_price(shopify_item, taxes_inclusive),
					"delivery_date": delivery_date,
					"qty": shopify_item.get("quantity"),
					"stock_uom": shopify_item.get("uom") or "Nos",
					"warehouse": setting.warehouse,
					ORDER_ITEM_DISCOUNT_FIELD: (
						_get_total_discount(shopify_item) / cint(shopify_item.get("quantity"))
					),
				}
			)
		else:
			items = []

	return items


def _get_item_price(line_item, taxes_inclusive: bool) -> float:

	price = flt(line_item.get("price"))
	qty = cint(line_item.get("quantity"))

	# remove line item level discounts
	total_discount = _get_total_discount(line_item)

	if not taxes_inclusive:
		return price - (total_discount / qty)

	total_taxes = 0.0
	for tax in line_item.get("tax_lines"):
		total_taxes += flt(tax.get("price"))

	return price - (total_taxes + total_discount) / qty

def _get_total_discount(line_item) -> float:
	discount_allocations = line_item.get("discount_allocations") or []
	return sum(flt(discount.get("amount")) for discount in discount_allocations)


def get_order_taxes(shopify_order, setting, items):
	taxes = []
	line_items = shopify_order.get("line_items")

	for line_item in line_items:
		item_code = get_item_code(line_item)
		for tax in line_item.get("tax_lines"):
			taxes.append(
				{
					"charge_type": "Actual",
					"account_head": get_tax_account_head(tax, charge_type="sales_tax"),
					"description": (
						get_tax_account_description(tax)
						or f"{tax.get('title')} - {tax.get('rate') * 100.0:.2f}%"
					),
					"tax_amount": tax.get("price"),
					"included_in_print_rate": 0,
					"cost_center": setting.cost_center,
					"item_wise_tax_detail": {item_code: [flt(tax.get("rate")) * 100, flt(tax.get("price"))]},
					"dont_recompute_tax": 1,
				}
			)

	update_taxes_with_shipping_lines(
		taxes,
		shopify_order.get("shipping_lines"),
		setting,
		items,
		taxes_inclusive=shopify_order.get("taxes_included"),
	)

	if cint(setting.consolidate_taxes):
		taxes = consolidate_order_taxes(taxes)

	for row in taxes:
		tax_detail = row.get("item_wise_tax_detail")
		if isinstance(tax_detail, dict):
			row["item_wise_tax_detail"] = json.dumps(tax_detail)

	return taxes


def consolidate_order_taxes(taxes):
	tax_account_wise_data = {}
	for tax in taxes:
		account_head = tax["account_head"]
		tax_account_wise_data.setdefault(
			account_head,
			{
				"charge_type": "Actual",
				"account_head": account_head,
				"description": tax.get("description"),
				"cost_center": tax.get("cost_center"),
				"included_in_print_rate": 0,
				"dont_recompute_tax": 1,
				"tax_amount": 0,
				"item_wise_tax_detail": {},
			},
		)
		tax_account_wise_data[account_head]["tax_amount"] += flt(tax.get("tax_amount"))
		if tax.get("item_wise_tax_detail"):
			tax_account_wise_data[account_head]["item_wise_tax_detail"].update(tax["item_wise_tax_detail"])

	return tax_account_wise_data.values()


def get_tax_account_head(tax, charge_type: Literal["shipping", "sales_tax"] | None = None):
	tax_title = str(tax.get("title"))

	tax_account = frappe.db.get_value(
		"Shopify Tax Account",
		{"parent": SETTING_DOCTYPE, "shopify_tax": tax_title},
		"tax_account",
	)

	if not tax_account and charge_type:
		tax_account = frappe.db.get_single_value(SETTING_DOCTYPE, DEFAULT_TAX_FIELDS[charge_type])

	if not tax_account:
		frappe.throw(_("Tax Account not specified for Shopify Tax {0}").format(tax.get("title")))

	return tax_account


def get_tax_account_description(tax):
	tax_title = tax.get("title")

	tax_description = frappe.db.get_value(
		"Shopify Tax Account",
		{"parent": SETTING_DOCTYPE, "shopify_tax": tax_title},
		"tax_description",
	)

	return tax_description


def update_taxes_with_shipping_lines(taxes, shipping_lines, setting, items, taxes_inclusive=False):
	"""Shipping lines represents the shipping details,
	each such shipping detail consists of a list of tax_lines"""
	shipping_as_item = cint(setting.add_shipping_as_item) and setting.shipping_item
	for shipping_charge in shipping_lines:
		if shipping_charge.get("price"):
			shipping_discounts = shipping_charge.get("discount_allocations") or []
			total_discount = sum(flt(discount.get("amount")) for discount in shipping_discounts)

			shipping_taxes = shipping_charge.get("tax_lines") or []
			total_tax = sum(flt(discount.get("price")) for discount in shipping_taxes)

			shipping_charge_amount = flt(shipping_charge["price"]) - flt(total_discount)
			if bool(taxes_inclusive):
				shipping_charge_amount -= total_tax

			if shipping_as_item:
				items.append(
					{
						"item_code": setting.shipping_item,
						"rate": shipping_charge_amount,
						"delivery_date": items[-1]["delivery_date"] if items else nowdate(),
						"qty": 1,
						"stock_uom": "Nos",
						"warehouse": setting.warehouse,
					}
				)
			else:
				taxes.append(
					{
						"charge_type": "Actual",
						"account_head": get_tax_account_head(shipping_charge, charge_type="shipping"),
						"description": get_tax_account_description(shipping_charge)
						or shipping_charge["title"],
						"tax_amount": shipping_charge_amount,
						"cost_center": setting.cost_center,
					}
				)

		for tax in shipping_charge.get("tax_lines"):
			taxes.append(
				{
					"charge_type": "Actual",
					"account_head": get_tax_account_head(tax, charge_type="sales_tax"),
					"description": (
						get_tax_account_description(tax)
						or f"{tax.get('title')} - {tax.get('rate') * 100.0:.2f}%"
					),
					"tax_amount": tax["price"],
					"cost_center": setting.cost_center,
					"item_wise_tax_detail": {
						setting.shipping_item: [flt(tax.get("rate")) * 100, flt(tax.get("price"))]
					}
					if shipping_as_item
					else {},
					"dont_recompute_tax": 1,
				}
			)

# def _get_item_price(line_item, taxes_inclusive: bool) -> float:
# 	price = flt(line_item.get("price"))
# 	qty = cint(line_item.get("quantity"))

# 	# remove line item level discounts
# 	total_discount = _get_total_discount(line_item)

# 	if not taxes_inclusive:
# 		return price - (total_discount / qty)

# 	total_taxes = 0.0
# 	for tax in line_item.get("tax_lines"):
# 		total_taxes += flt(tax.get("price"))

# 	calculated_rate = price - (total_taxes + total_discount) / qty
	
# 	# If rate is negative, calculate using tax rates
# 	if calculated_rate < 0:
# 		price = flt(line_item.get("price"))
# 		sku = line_item.get("sku")
# 		print(price,sku)

# 		tax_template = frappe.db.get_value("Item Tax",{"parent":sku},"item_tax_template")
# 		if tax_template:
# 			tax_rate = frappe.db.get_value("Item Tax Template",{"name":tax_template,"disabled":0},"gst_rate")
# 			if tax_rate:
# 				gst_rate  = ((price * (tax_rate / 100)) / (100 + tax_rate)) * 100
# 				calculated_rate = price - gst_rate
	
# 	return calculated_rate


# def get_order_taxes(shopify_order, setting, items):
# 	try:
# 		unsorted_taxes = []
# 		line_items = shopify_order.get("line_items", [])

# 		for line_item in line_items:
# 			item_code = get_item_code(line_item)
# 			for tax in line_item.get("tax_lines", []):
# 				account_head, charge_type, order_sequence = get_tax_account_head(tax, charge_type="sales_tax")

# 				tax_rate = flt(tax.get("rate")) * 100
# 				tax_amount = flt(tax.get("price"))

# 				unsorted_taxes.append({
# 					"charge_type": charge_type,
# 					"account_head": account_head,
# 					"order_sequence": order_sequence,
# 					"rate":tax_rate,
# 					"description": get_tax_account_description(tax) or f"{tax.get('title')} - {tax_rate:.2f}%",
# 					"tax_amount": tax_amount,
# 					"included_in_print_rate": 0,
# 					"cost_center": setting.cost_center,
# 					"item_wise_tax_detail": {item_code: [tax_rate, tax_amount]},
# 					"dont_recompute_tax": 1,
# 				})

# 		if shopify_order.get("shipping_lines"):
# 			update_taxes_with_shipping_lines(
# 				unsorted_taxes,
# 				shopify_order.get("shipping_lines", []),
# 				setting,
# 				items,
# 				taxes_inclusive=shopify_order.get("taxes_included"),
# 			)
# 		else:
# 			shipping_charge = {"title": "Standard Shipping"}
# 			shipping_charge_amount = flt(getattr(setting, "default_shipping_amount", 0.0))

# 			account_head, charge_type, order_sequence = get_tax_account_head(
# 				shipping_charge, charge_type="shipping"
# 			)

# 			unsorted_taxes.append(
# 				{
# 					"charge_type": charge_type,
# 					"account_head": account_head,
# 					"order_sequence": order_sequence,
# 					"rate":tax_rate,
# 					"description": get_tax_account_description(shipping_charge) or shipping_charge["title"],
# 					"tax_amount": shipping_charge_amount,
# 					"cost_center": setting.cost_center,
# 					"dont_recompute_tax": 1,
# 				}
# 			)

# 		if cint(setting.consolidate_taxes):
# 			unsorted_taxes = consolidate_order_taxes(unsorted_taxes)

# 		print(unsorted_taxes)
# 		unsorted_taxes = consolidate_taxes_by_account_head(unsorted_taxes)
# 		sorted_taxes = sorted(unsorted_taxes, key=lambda x: x.get("order_sequence") or 0)

# 		last_independent_row_idx = None

# 		for idx, row in enumerate(sorted_taxes):
# 			if row["charge_type"] in ["On Previous Row Amount", "On Previous Row Total"]:
# 				row["row_id"] = last_independent_row_idx + 1 if last_independent_row_idx is not None else 1
# 			else:
# 				last_independent_row_idx = idx

# 			if isinstance(row.get("item_wise_tax_detail"), dict):
# 				row["item_wise_tax_detail"] = json.dumps(row["item_wise_tax_detail"])

# 		print(sorted_taxes)
# 		return sorted_taxes
# 	except Exception as e:
# 		frappe.log_error(message=frappe.get_traceback(),title="Shopify Order Tax Sync Failed")

# def consolidate_taxes_by_account_head(taxes):
# 	tax_account_wise_data = {}
# 	for tax in taxes:
# 		account_head = tax["account_head"]
# 		charge_type = tax["charge_type"]

# 		# Determine tax rate based on account head
# 		tax_rate = 18.0 if "IGST" in account_head else 9.0 if "CGST" in account_head or "SGST" in account_head else 0.0

# 		# Initialize dictionary for this account head if not already present
# 		tax_account_wise_data.setdefault(
# 			account_head,
# 			{
# 				"charge_type": charge_type,
# 				"account_head": account_head,
# 				"description": tax.get("description"),
# 				"cost_center": tax.get("cost_center"),
# 				"order_sequence": tax.get("order_sequence"),
# 				"included_in_print_rate": 0,
# 				"dont_recompute_tax": 1,
# 				"tax_amount": 0,
# 				"rate": tax_rate,
# 				"item_wise_tax_detail": {},
# 			},
# 		)

# 		# Add tax amount
# 		tax_account_wise_data[account_head]["tax_amount"] += flt(tax.get("tax_amount"))

# 		# Parse and update item_wise_tax_detail if present
# 		if tax.get("item_wise_tax_detail"):
# 			tax_account_wise_data[account_head]["item_wise_tax_detail"].update(tax["item_wise_tax_detail"])

# 	return list(tax_account_wise_data.values())


# def consolidate_order_taxes(taxes):
# 	tax_account_wise_data = {}
# 	for tax in taxes:
# 		account_head = tax["account_head"]
# 		charge_type = tax["charge_type"]
# 		tax_account_wise_data.setdefault(
# 			account_head,
# 			{
# 				"charge_type": charge_type,
# 				"account_head": account_head,
# 				"description": tax.get("description"),
# 				"cost_center": tax.get("cost_center"),
# 				"included_in_print_rate": 0,
# 				"dont_recompute_tax": 1,
# 				"tax_amount": 0,
# 				"item_wise_tax_detail": {},
# 			},
# 		)
# 		tax_account_wise_data[account_head]["tax_amount"] += flt(tax.get("tax_amount"))
# 		if tax.get("item_wise_tax_detail"):
# 			tax_account_wise_data[account_head]["item_wise_tax_detail"].update(tax["item_wise_tax_detail"])

# 	return tax_account_wise_data.values()


# def get_tax_account_head(tax, charge_type: Optional[Literal["shipping", "sales_tax"]] = None):
# 	tax_title = str(tax.get("title"))

# 	tax_account_data = frappe.db.get_value(
# 		"Shopify Tax Account",
# 		{"parent": SETTING_DOCTYPE, "shopify_tax": tax_title},
# 		["tax_account", "charge_type","order_sequence"],
# 		as_dict=True,
# 	)

# 	tax_account = tax_account_data.tax_account if tax_account_data else None
# 	chargeable_type = tax_account_data.charge_type if tax_account_data else "Actual"
# 	order_sequence = tax_account_data.order_sequence if tax_account_data else 0

# 	if not tax_account and charge_type:
# 		tax_account = frappe.db.get_single_value(SETTING_DOCTYPE, DEFAULT_TAX_FIELDS[charge_type])

# 	if not tax_account:
# 		frappe.throw(_("Tax Account not specified for Shopify Tax {0}").format(tax.get("title")))

# 	return tax_account, chargeable_type, order_sequence


# def get_tax_account_description(tax):
# 	tax_title = tax.get("title")

# 	tax_description = frappe.db.get_value(
# 		"Shopify Tax Account", {"parent": SETTING_DOCTYPE, "shopify_tax": tax_title}, "tax_description",
# 	)

# 	return tax_description


# def update_taxes_with_shipping_lines(taxes, shipping_lines, setting, items, taxes_inclusive=False):
# 	"""Shipping lines represents the shipping details,
# 	each such shipping detail consists of a list of tax_lines"""
# 	shipping_as_item = cint(setting.add_shipping_as_item) and setting.shipping_item
# 	for shipping_charge in shipping_lines:
# 		if shipping_charge.get("price"):
# 			shipping_discounts = shipping_charge.get("discount_allocations") or []
# 			total_discount = sum(flt(discount.get("amount")) for discount in shipping_discounts)

# 			shipping_taxes = shipping_charge.get("tax_lines") or []
# 			total_tax = sum(flt(discount.get("price")) for discount in shipping_taxes)

# 			shipping_charge_amount = flt(shipping_charge["price"]) - flt(total_discount)
# 			if bool(taxes_inclusive):
# 				shipping_charge_amount -= total_tax

# 			if shipping_as_item:
# 				items.append(
# 					{
# 						"item_code": setting.shipping_item,
# 						"rate": shipping_charge_amount,
# 						"delivery_date": items[-1]["delivery_date"] if items else nowdate(),
# 						"qty": 1,
# 						"stock_uom": "Nos",
# 						"warehouse": setting.warehouse,
# 					}
# 				)
# 			else:
# 				account_head, charge_type, order_sequence = get_tax_account_head(shipping_charge, charge_type="shipping")
# 				taxes.append(
# 					{
# 						"charge_type": charge_type,
# 						"account_head": account_head,
# 						"order_sequence": order_sequence,
# 						"description": get_tax_account_description(shipping_charge) or shipping_charge["title"],
# 						"tax_amount": shipping_charge_amount,
# 						"cost_center": setting.cost_center,
# 						"dont_recompute_tax": 1,
# 					}
# 				)

# 		for tax in shipping_charge.get("tax_lines"):
# 			account_head, charge_type, order_sequence = get_tax_account_head(tax, charge_type="sales_tax")
# 			taxes.append(
# 				{
# 					"charge_type": charge_type,
# 					"account_head": account_head,
# 					"order_sequence": order_sequence,
# 					"description": (
# 						get_tax_account_description(tax) or f"{tax.get('title')} - {tax.get('rate') * 100.0:.2f}%"
# 					),
# 					"tax_amount": tax["price"],
# 					"cost_center": setting.cost_center,
# 					"item_wise_tax_detail": {
# 						setting.shipping_item: [flt(tax.get("rate")) * 100, flt(tax.get("price"))]
# 					}
# 					if shipping_as_item
# 					else {},
# 					"dont_recompute_tax": 1,
# 				}
# 			)


def get_sales_order(order_id):
	"""Get ERPNext sales order using shopify order id."""
	sales_order = frappe.db.get_value("Sales Order", filters={ORDER_ID_FIELD: order_id})
	if sales_order:
		return frappe.get_doc("Sales Order", sales_order)


def cancel_order(payload, request_id=None):
	"""Called by order/cancelled event.

	When shopify order is cancelled there could be many different someone handles it.

	Updates document with custom field showing order status.

	IF sales invoice / delivery notes are not generated against an order, then cancel it.
	"""
	frappe.set_user("Administrator")
	frappe.flags.request_id = request_id

	order = payload

	try:
		order_id = order["id"]
		order_status = order["financial_status"]

		sales_order = get_sales_order(order_id)

		if not sales_order:
			create_shopify_log(status="Invalid", message="Sales Order does not exist")
			return

		sales_invoice = frappe.db.get_value("Sales Invoice", filters={ORDER_ID_FIELD: order_id})
		delivery_notes = frappe.db.get_list("Delivery Note", filters={ORDER_ID_FIELD: order_id})

		if sales_invoice:
			frappe.db.set_value("Sales Invoice", sales_invoice, ORDER_STATUS_FIELD, order_status)

		for dn in delivery_notes:
			frappe.db.set_value("Delivery Note", dn.name, ORDER_STATUS_FIELD, order_status)

		if not sales_invoice and not delivery_notes and sales_order.docstatus == 1:
			sales_order.cancel()
		else:
			frappe.db.set_value("Sales Order", sales_order.name, ORDER_STATUS_FIELD, order_status)

	except Exception as e:
		create_shopify_log(status="Error", exception=e)
	else:
		create_shopify_log(status="Success")


@temp_shopify_session
def sync_old_orders():
	try:

		frappe.log_error("Syncing Old Orders")
		shopify_setting = frappe.get_cached_doc(SETTING_DOCTYPE)
		if not cint(shopify_setting.sync_old_orders):
			frappe.log_error("Sync Old Orders is disabled")
			return

		orders = _fetch_old_orders(shopify_setting.old_orders_from, shopify_setting.old_orders_to)

		frappe.log_error(title="Orders Fetched", message=str(orders))

		for order in orders:
			log = create_shopify_log(
				method=EVENT_MAPPER["orders/create"], request_data=json.dumps(order), make_new=True
			)
			sync_sales_order(order, request_id=log.name)

		shopify_setting = frappe.get_doc(SETTING_DOCTYPE)
		shopify_setting.sync_old_orders = 0
		shopify_setting.save()
	except Exception:
		frappe.log_error(title="Sync Old Orders", message=frappe.get_traceback())


def _fetch_old_orders(from_time, to_time):
	"""Fetch all shopify orders in specified range and return an iterator on fetched orders."""
	frappe.log_error(title="Fetching Orders from {} to {}".format(str(from_time), str(to_time)))
	from_time = get_datetime(from_time).astimezone().isoformat()
	to_time = get_datetime(to_time).astimezone().isoformat()

	orders_iterator = PaginatedIterator(
		Order.find(created_at_min=from_time, created_at_max=to_time, limit=250)
	)

	for orders in orders_iterator:
		for order in orders:
			# Using generator instead of fetching all at once is better for
			# avoiding rate limits and reducing resource usage.
			yield order.to_dict()