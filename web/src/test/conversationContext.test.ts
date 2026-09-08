import { describe, expect, it } from "vitest";
import { recentConversationContext } from "@/lib/conversation";

describe("conversation context", () => {
  it("excludes failed submissions while preserving the last question", () => {
    const result = recentConversationContext([
      { id: "1", role: "user", content: "推荐酒店" },
      { id: "2", role: "assistant", content: "希望住哪里？" },
      { id: "3", role: "user", content: "失败的请求", failed: true },
    ]);
    expect(result).toEqual([
      { role: "user", content: "推荐酒店" },
      { role: "assistant", content: "希望住哪里？" },
    ]);
  });
});
