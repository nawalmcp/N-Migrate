# Third-Party SDK Notice

## VMware/Broadcom vCenter Converter Standalone SDK

`n_migrate/integrations/converter_standalone.py` provides optional,
experimental integration with a user-run VMware/Broadcom vCenter
Converter Standalone server, for real Physical-to-Virtual (P2V)
migration.

**Nothing from Broadcom's Converter Standalone SDK is vendored,
copied, or redistributed in this repository.** That SDK (freely
downloadable from Broadcom, distributed under a "Software Development
Kit License Agreement") restricts redistribution to files it
explicitly designates as "distributable code" at a Broadcom-hosted
URL referenced in the license text -- we cannot confirm any of our
own logic matches that designation, so out of caution nothing from
the SDK zip -- not the WSDL, not the sample code, not the bundled
Converter-specific pyVmomi extensions -- ships here.

Instead, `converter_standalone.py` is a clean-room SOAP client:

- Written against the Converter Standalone **Reference Guide**'s
  published operation/type/field documentation (which describes a
  wire protocol, not licensed source code).
- Uses `zeep`, an independent open-source (MIT-licensed) SOAP
  library, instead of VMware's bundled client code.
- Fetches the WSDL directly from **your own** Converter Standalone
  server at connect() time -- ordinary SOAP client behavior, no
  VMware files needed on disk anywhere in this project or its
  dependencies.

If you want VMware's own sample code or full API reference for
comparison while developing against this module, download the
Converter Standalone SDK yourself, directly from Broadcom -- it's
free, we just can't embed it here.

This module is unverified against a real server (see its module
docstring and `LAB_TESTING.md` for specifics) -- treat it as a
starting point for your own validation, not a finished integration.

## Everything else

`pyVmomi` (vSphere API bindings) and `ovftool` are used elsewhere in
this project (`adapters/*/vmware.py`) under their own respective
licenses (pyVmomi: Apache 2.0, freely redistributable and already a
normal PyPI dependency; ovftool: proprietary but freely downloadable,
installed by the user directly, never bundled here) -- see the main
README's Requirements table.
