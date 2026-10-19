import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Mono } from "@/components/Mono";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { copyText } from "@/lib/copy";

export function TokenReveal({ token, testId = "token-plaintext" }: { token: string; testId?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs font-medium">Token</span>
      <div className="flex items-stretch gap-2">
        <code className="flex min-w-0 flex-1 items-center rounded-md border border-border bg-background px-3 py-2">
          <Mono title={token}>
            <span data-testid={testId} className="break-all">{token}</span>
          </Mono>
        </code>
        <Button
          type="button"
          variant={copied ? "outline" : "default"}
          className="h-auto"
          data-testid="token-copy"
          aria-label="Copy token"
          onClick={() => {
            void copyText(token).then(() => setCopied(true));
          }}
        >
          {copied ? <Check size={14} strokeWidth={2} aria-hidden="true" /> : <Copy size={14} strokeWidth={2} aria-hidden="true" />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <Notice tone="warning">You cannot see this token again after you close this window. Create a new one if it is lost.</Notice>
    </div>
  );
}
