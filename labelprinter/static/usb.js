"use strict";
// WebUSB printing: Chrome on the Android tablet with the printer on a USB OTG cable.
// The page asks Chrome for the device once; Chrome then remembers the permission.
window.UsbPrinter = (() => {
  let device = null;
  let endpoint = null;
  const CHUNK = 16384;

  function supported() {
    return !!navigator.usb;
  }

  async function connect() {
    if (!supported()) throw new Error("This browser cannot use USB. Open the page in Chrome on the Android tablet.");
    const known = await navigator.usb.getDevices();
    device = known[0] || await navigator.usb.requestDevice({ filters: [] });
    await device.open();
    if (device.configuration === null) await device.selectConfiguration(1);
    let found = null;
    for (const iface of device.configuration.interfaces) {
      for (const alt of iface.alternates) {
        const out = alt.endpoints.find((e) => e.direction === "out" && e.type === "bulk");
        if (alt.interfaceClass === 0x07 && out) found = { number: iface.interfaceNumber, alt: alt.alternateSetting, out: out.endpointNumber };
      }
    }
    if (!found) throw new Error("This USB device is not a printer (no printer interface with a bulk OUT endpoint).");
    await device.claimInterface(found.number);
    if (found.alt !== 0) await device.selectAlternateInterface(found.number, found.alt);
    endpoint = found.out;
  }

  async function ensure() {
    if (!device || !device.opened || endpoint === null) await connect();
  }

  async function send(bytes) {
    await ensure();
    for (let offset = 0; offset < bytes.length; offset += CHUNK) {
      const result = await device.transferOut(endpoint, bytes.slice(offset, offset + CHUNK));
      if (result.status !== "ok") throw new Error("Printer did not accept the data (" + result.status + ").");
    }
  }

  if (supported()) {
    navigator.usb.addEventListener("disconnect", () => { device = null; endpoint = null; });
  }
  return { supported, send };
})();
