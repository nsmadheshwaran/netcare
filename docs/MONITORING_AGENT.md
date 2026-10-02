# Monitoring agent

> **Status: not implemented.** Planned for Phase 6. This page records the design rules the implementation
> must follow.

## Design rules
- Installed explicitly by an administrator on an authorized customer network. It is visible as a normal
  Windows service and appears in *Installed apps*.
- **Outbound HTTPS only.** No inbound ports are opened on the customer network.
- Authenticates with a unique, revocable per-agent token. The server stores only a hash of it, and revoking
  the token in NetCare stops the agent immediately.
- Collects only what is configured for that agent: ICMP reachability, TCP connects to explicitly listed
  ports, and optionally SNMP read-only metrics from listed devices.
- Queues results locally and retries with backoff while offline.
- **Never**: network discovery or scanning beyond the configured targets, credential guessing, exploitation,
  arbitrary remote command execution, hidden persistence, or collection of personal files, keystrokes or
  messages.
- Documented install and uninstall steps will be added here when the agent is built.
