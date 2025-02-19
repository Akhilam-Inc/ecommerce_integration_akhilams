// Copyright (c) 2021, Frappe and contributors
// For license information, please see LICENSE

frappe.provide("ecommerce_integrations.shopify.shopify_setting");

frappe.ui.form.on("Shopify Setting", {
	onload: function (frm) {
		frappe.call({
			method: "ecommerce_integrations.utils.naming_series.get_series",
			callback: function (r) {
				$.each(r.message, (key, value) => {
					set_field_options(key, value);
				});
			},
		});
	},

	fetch_shopify_locations: function (frm) {
		frappe.call({
			doc: frm.doc,
			method: "update_location_table",
			callback: (r) => {
				if (!r.exc) refresh_field("shopify_warehouse_mapping");
			},
		});
	},

	refresh: function (frm) {
		frm.add_custom_button(__("Update Shipping Details"), function () {
            frappe.prompt([
                {
                    label: 'Order ID',
                    fieldname: 'order_id',
                    fieldtype: 'Data',
                    reqd: 1
                },
                {
                    label: 'Tracking Number',
                    fieldname: 'tracking_number',
                    fieldtype: 'Data',
                    reqd: 1
                }
            ], function(values){
                frappe.call({
                    method: "ecommerce_integrations.api.update_shipping_details",
                    args: {
                        order_id: values.order_id,
                        tracking_string: values.tracking_number
                    },
					freeze: true,
                    callback: function(r) {
                        try {
                            if (!r.exc) {
                                const msg = `Order ${values.order_id} with tracking number ${values.tracking_number} Shipping details updated successfully`;
                                frappe.show_alert({
                                    message: __(msg),
                                    indicator: 'green'
                                }, 5);
                            }
                        } catch (e) {
                            console.error("Error updating shipping details:", e);
                            frappe.show_alert({
                                message: __("Failed to update shipping details"),
                                indicator: 'red'
                            }, 5);
                        }
                    },
                    error: function(r) {
                        frappe.show_alert({
                            message: __("Failed to update shipping details"),
                            indicator: 'red'
                        }, 5);
                    }
                });
            }, __('Update Shipping Details'), __('Update'));
        });
		frm.add_custom_button(__("Import Products"), function () {
			frappe.set_route("shopify-import-products");
		});
		
		frm.add_custom_button(__("View Logs"), () => {
			frappe.set_route("List", "Ecommerce Integration Log", {
				integration: "Shopify",
			});
		});
		frm.trigger("setup_queries");
	},

	setup_queries: function (frm) {
		const warehouse_query = () => {
			return {
				filters: {
					company: frm.doc.company,
					disabled: 0,
				},
			};
		};
		frm.set_query("warehouse", warehouse_query);
		frm.set_query(
			"erpnext_warehouse",
			"shopify_warehouse_mapping",
			warehouse_query
		);
		frm.set_query("price_list", () => {
			return {
				filters: {
					selling: 1,
				},
			};
		});

		frm.set_query("cost_center", () => {
			return {
				filters: {
					company: frm.doc.company,
					is_group: "No",
				},
			};
		});

		frm.set_query("cash_bank_account", () => {
			return {
				filters: [
					["Account", "account_type", "in", ["Cash", "Bank"]],
					["Account", "root_type", "=", "Asset"],
						["Account", "is_group", "=", 0],
					["Account", "company", "=", frm.doc.company],
				],
			};
		});

		const tax_query = () => {
			return {
				query: "erpnext.controllers.queries.tax_account_query",
				filters: {
					account_type: ["Tax", "Chargeable", "Expense Account"],
					company: frm.doc.company,
				},
			};
		};

		frm.set_query("tax_account", "taxes", tax_query);
		frm.set_query("default_sales_tax_account", tax_query);
		frm.set_query("default_shipping_charges_account", tax_query);
	},
});
