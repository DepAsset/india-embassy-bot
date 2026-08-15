from pathlib import Path

path = Path("src/rajdoot/embassy_workflow.py")
text = path.read_text()

block = '''    if own_country:\n        diplomats = await store.active_embassy_members(str(embassy["id"]))\n        if not diplomats:\n            await store.set_flow_state(\n                request_id,\n                "approved_new_or_unstaffed_embassy",\n                request_status="approved",\n                government_auto_approved=True,\n                target_country_id=str(embassy.get("country_id") or country_id or ""),\n                target_embassy_id=str(embassy["id"]),\n            )\n            await EmbassyAccessService(database).grant(\n                applicant.guild,\n                applicant,\n                embassy,\n                actor_id=None,\n                assignment_type="foreign_diplomat",\n            )\n            await store.log_audit(\n                actor=applicant.id,\n                action="UNSTAFFED_EMBASSY_AUTO_APPROVED",\n                target_type="request",\n                target_id=request_id,\n                embassy_id=str(embassy["id"]),\n                result="APPROVED",\n                metadata={"reason": "no_active_diplomats"},\n            )\n            if channel:\n                await channel.send(\n                    f"🟢 **{embassy['country_name']} Embassy access granted.** "\n                    "This embassy currently has no active diplomats, so no approval step was required."\n                )\n            await close_thread(channel)\n            return\n\n'''

if block not in text:
    raise SystemExit("Unstaffed embassy block is missing")

# If already after the government-official branch, leave it alone.
gov_marker = '    if own_country and position in {"President", "Vice President", "Minister of Foreign Affairs"}:'
gov_start = text.find(gov_marker)
if gov_start < 0:
    raise SystemExit("Government official branch missing")

gov_return = text.find("        return\n", gov_start)
if gov_return < 0:
    raise SystemExit("Government official branch return missing")
gov_end = gov_return + len("        return\n")

block_pos = text.find(block)
if block_pos > gov_end:
    print("Unstaffed embassy auto-approval precedence already correct")
else:
    text = text[:block_pos] + text[block_pos + len(block):]
    # Recalculate government branch after removal.
    gov_start = text.find(gov_marker)
    gov_return = text.find("        return\n", gov_start)
    gov_end = gov_return + len("        return\n")
    text = text[:gov_end] + "\n" + block + text[gov_end:]
    path.write_text(text)
    print("Moved unstaffed embassy auto-approval after preapproval/government-official checks")
