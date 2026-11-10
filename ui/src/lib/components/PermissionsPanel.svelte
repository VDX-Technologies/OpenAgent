<script lang="ts">
  import { onMount } from "svelte";
  import { getPermissions, setPermission, type Permission } from "#lib/api";
  import Panel from "./Panel.svelte";
  import Switch from "./Switch.svelte";

  /** Which actions run without asking. Everything else shows an approval card first. */
  let items = $state<Permission[]>([]);
  const load = () => getPermissions().then((r) => (items = r.permissions)).catch(() => {});
  onMount(() => {
    load();
    // "Always allow" on an approval card (here or in another window) turns a switch on
    const onVisible = () => document.visibilityState === "visible" && load();
    window.addEventListener("vdx:permissions-changed", load);
    window.addEventListener("focus", load);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("vdx:permissions-changed", load);
      window.removeEventListener("focus", load);
      document.removeEventListener("visibilitychange", onVisible);
    };
  });

  async function toggle(p: Permission) {
    try { items = (await setPermission(p.tool, !p.always)).permissions; } catch { /* keep the old state */ }
  }
</script>

<Panel title="Permissions">
  <p class="-mt-2 mb-3 text-[12.5px] text-[var(--text-muted)]">
    VDX asks before it sends, deletes or publishes anything. Switch on the actions it may do without asking —
    automations and Discord can only run actions that are switched on here.
  </p>
  <div class="grid gap-x-6 md:grid-cols-2">
    {#each items as p (p.tool)}
      <button type="button" role="switch" aria-checked={p.always} onclick={() => toggle(p)}
        class="flex items-center justify-between gap-3 rounded-lg px-2 py-2 text-left text-[12.5px] hover:bg-[var(--bg-hover)]">
        <span>{p.label}</span><Switch on={p.always} size="sm" />
      </button>
    {/each}
  </div>
</Panel>
