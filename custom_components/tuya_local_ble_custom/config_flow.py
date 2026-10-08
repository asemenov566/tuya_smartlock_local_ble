"""Discover nearby locks, collect owner credentials, verify a read-only session."""

from __future__ import annotations

import asyncio

import voluptuous as vol
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import CONF_KEEP_CONNECTED, DOMAIN
from .keyman import LocalCredentialProvider
from .registry import MODELS, create_connection, discovery_services


class SmartlockConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._devices = {}
        self._address = None
        self._product_id = next(iter(MODELS))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SmartlockOptionsFlow()

    async def async_step_bluetooth(self, discovery_info):
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._devices[discovery_info.address] = discovery_info
        self.context["title_placeholders"] = {
            "name": f"FD50 {discovery_info.address[-8:]}"
        }
        return await self.async_step_user()

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            if self._address not in self._devices:
                return self.async_abort(reason="no_unconfigured_devices")
            await self.async_set_unique_id(self._address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self.async_step_model()
        current = self._async_current_ids()
        for info in bluetooth.async_discovered_service_info(self.hass):
            if info.address not in current and discovery_services().intersection(
                info.service_data or {}
            ):
                self._devices[info.address] = info
        if not self._devices:
            return self.async_abort(reason="no_unconfigured_devices")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            address: f"{info.name} ({address})"
                            for address, info in self._devices.items()
                        }
                    )
                }
            ),
        )

    async def async_step_model(self, user_input=None):
        if user_input is not None:
            self._product_id = user_input["product_id"]
            return await self.async_step_credentials()
        if len(MODELS) == 1:
            self._product_id = next(iter(MODELS))
            return await self.async_step_credentials()
        return self.async_show_form(
            step_id="model",
            data_schema=vol.Schema(
                {
                    vol.Required("product_id"): vol.In(
                        {key: cls.name for key, cls in MODELS.items()}
                    )
                }
            ),
        )

    async def async_step_credentials(self, user_input=None):
        errors = {}
        model = MODELS[self._product_id]
        if user_input is not None:
            values = {
                key: user_input.get(key, "").strip() for key in model.credential_fields
            }
            if not model.validate_credentials(values):
                errors["base"] = "invalid_credentials"
            else:
                values["product_id"] = model.product_id
                values["category"] = model.category
                values["device_name"] = model.name
                values["product_name"] = model.name
                values["product_model"] = model.name
                data = {CONF_ADDRESS: self._address, "credentials": values}
                provider = LocalCredentialProvider(self.hass, data)
                credentials = await provider.get_device_credentials(self._address)
                device = None
                try:
                    device, _ = create_connection(
                        credentials, provider, self._devices[self._address].device
                    )
                    device.managed_connection = True
                    async with asyncio.timeout(90):
                        await device.initialize()
                        await device.update()
                except Exception:
                    errors["base"] = "cannot_connect"
                finally:
                    if device is not None:
                        try:
                            await device.stop()
                        except Exception:
                            errors["base"] = "cannot_connect"
                if not errors:
                    return self.async_create_entry(
                        title=f"{model.name} {self._address.replace(':', '')[-6:]}",
                        data=data,
                        options={CONF_KEEP_CONNECTED: True},
                    )
        # Legacy file support is optional; never read another integration's data.
        # Only non-secret model selection receives a default; secrets are never echoed.
        fields = {}
        for key in model.credential_fields:
            fields[vol.Required(key)] = selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            )
        return self.async_show_form(
            step_id="credentials", data_schema=vol.Schema(fields), errors=errors
        )


class SmartlockOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    **self.config_entry.options,
                    CONF_KEEP_CONNECTED: bool(
                        user_input.get(CONF_KEEP_CONNECTED, True)
                    ),
                },
            )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_KEEP_CONNECTED,
                        default=self.config_entry.options.get(
                            CONF_KEEP_CONNECTED, True
                        ),
                    ): bool
                }
            ),
        )
