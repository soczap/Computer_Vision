import IdentityProfile from "../IdentityProfile";
import { FrsShell } from "./common";

/** The shared profile (timeline, cameras, detections, FRS search history) inside the FRS workspace. */
export default function FrsIdentity() {
  return (
    <FrsShell title="Identity profile" subtitle="Appearances, camera history, detection history and every FRS watchlist search made for this person">
      <IdentityProfile embedded />
    </FrsShell>
  );
}
