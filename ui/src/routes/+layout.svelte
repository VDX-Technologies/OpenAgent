<script lang="ts">
  import "../app.css";
  import Sidebar from "#lib/components/Sidebar.svelte";
  import Onboarding from "#lib/components/Onboarding.svelte";
  import ConsentBanner from "#lib/components/ConsentBanner.svelte";
  import Toasts from "#lib/components/Toasts.svelte";
  import ConfirmDialog from "#lib/components/ConfirmDialog.svelte";
  import UpdateBanner from "#lib/components/UpdateBanner.svelte";
  let { children } = $props();
</script>

<svelte:head><title>VDX OpenAgent</title></svelte:head>

<div class="pywebview-drag-region titlebar-strip"></div>
<div class="app-shell flex h-screen overflow-hidden">
  <Sidebar />
  <main class="relative flex min-w-0 flex-1 flex-col">{@render children()}</main>
  <Onboarding />
  <ConsentBanner />
  <Toasts />
  <ConfirmDialog />
  <UpdateBanner />
</div>
