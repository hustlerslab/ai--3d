"use client";

/**
 * Lighting and post-processing for the walkthrough canvas.
 *
 * Plain lights only — no drei SoftShadows (its injected PCSS GLSL references
 * helpers removed in three r185) and no drei Environment/Lightformer cubemap
 * (silently blanks the frame on this three/drei pairing). The warm-interior
 * read comes from a sun-like key with soft shadows, a cool fill, a hemisphere
 * bounce, and the per-room practicals that SceneMeshes adds from scene data.
 */

import {
  Bloom,
  EffectComposer,
  Vignette,
} from "@react-three/postprocessing";

export function SceneEnvironment() {
  return (
    <>
      <ambientLight intensity={0.35} color="#fff4e2" />
      <hemisphereLight args={["#fdf3e0", "#57503f", 0.5]} />
      {/* Key: warm low sun angled through the north windows */}
      <directionalLight
        position={[4, 7, -8]}
        intensity={1.5}
        color="#ffe9c4"
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-bias={-0.0004}
        shadow-camera-left={-14}
        shadow-camera-right={14}
        shadow-camera-top={14}
        shadow-camera-bottom={-14}
        shadow-camera-far={40}
      />
      {/* Fill: cool bounce from the opposite side */}
      <directionalLight position={[-6, 5, 8]} intensity={0.35} color="#dbe4ec" />

      <EffectComposer multisampling={4}>
        <Bloom
          intensity={0.5}
          luminanceThreshold={0.85}
          luminanceSmoothing={0.3}
          mipmapBlur
        />
        <Vignette eskil={false} offset={0.14} darkness={0.38} />
      </EffectComposer>
    </>
  );
}
