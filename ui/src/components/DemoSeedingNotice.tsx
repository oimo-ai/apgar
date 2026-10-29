import { Notice } from "@/components/ui/notice";

export function DemoSeedingNotice() {
  return (
    <Notice testId="demo-seeding-notice" title="Loading demo data">
      Apgar is replaying the first hours of each demo release, so releases and verdicts fill in over the next minute.
    </Notice>
  );
}
