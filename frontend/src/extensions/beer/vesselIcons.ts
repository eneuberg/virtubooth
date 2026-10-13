/**
 * The bottle and cup silhouettes as lucide icons (for the Flasche/Becher toggle):
 * the Beer Cam outline paths, scaled into lucide's 24×24 grid and filled.
 */
import { createLucideIcon, type LucideIcon } from 'lucide-react';
import { VESSEL_SHAPES, vesselIconTransform, type Vessel } from '@/sdk/camera/overlays';

function vesselIcon(vessel: Vessel): LucideIcon {
  return createLucideIcon(`vessel-${vessel}`, [
    [
      'path',
      {
        d: VESSEL_SHAPES[vessel].outline,
        transform: vesselIconTransform(vessel),
        fill: 'currentColor',
        stroke: 'none',
        key: vessel,
      },
    ],
  ]);
}

export const VESSEL_ICONS: Record<Vessel, LucideIcon> = {
  bottle: vesselIcon('bottle'),
  cup: vesselIcon('cup'),
};
