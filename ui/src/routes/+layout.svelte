<script lang="ts">
  import "../app.css";
  import { page } from "$app/state";
  import Sidebar from "#lib/components/Sidebar.svelte";
  import Onboarding from "#lib/components/Onboarding.svelte";
  import ConsentBanner from "#lib/components/ConsentBanner.svelte";
  import Toasts from "#lib/components/Toasts.svelte";
  import ConfirmDialog from "#lib/components/ConfirmDialog.svelte";
  import UpdateBanner from "#lib/components/UpdateBanner.svelte";
  let { children } = $props();
  // the quick-ask panel (⌥Space) is its own small window: no sidebar or banners
  const quick = $derived(page.url.pathname.startsWith("/quick"));
</script>

<svelte:head><title>VDX OpenAgent</title></svelte:head>

{#if quick}
  {@render children()}
{:else}
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
{/if}
