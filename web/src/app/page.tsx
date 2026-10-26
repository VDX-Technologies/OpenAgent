import { Suspense } from "react";
import { ChatView } from "@/components/ChatView";

export default function HomePage() {
  return (
    <Suspense fallback={null}>
      <ChatView />
    </Suspense>
  );
}
