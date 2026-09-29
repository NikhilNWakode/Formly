"use client";

import {
  Component,
  Suspense,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, useGLTF } from "@react-three/drei";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";

export interface ModelViewerHandle {
  resetView: () => void;
}

interface ModelViewerProps {
  url: string;
  ref?: React.Ref<ModelViewerHandle>;
  onLoaded?: () => void;
  onError?: (error: unknown) => void;
}

/**
 * Normalises whatever the provider produced into something that renders well.
 *
 * Shap-E output (verified against real output during development) has:
 *   - no materials at all
 *   - no NORMAL attribute
 *   - a COLOR_0 vertex-colour attribute
 *
 * glTF's default material is metalness = 1, roughness = 1, which renders almost
 * black without an environment map, and missing normals mean nothing is shaded
 * at all. Both are fixed here rather than assumed away, so the viewer also
 * behaves for providers that *do* ship materials.
 */
function usePreparedScene(scene: THREE.Group): THREE.Group {
  return useMemo(() => {
    // Clone so React StrictMode double-invocation and the drei cache cannot
    // leave us mutating a shared scene graph twice.
    //
    // Object3D.clone() SHARES geometry and material references with the cached
    // original, so the clone must never dispose them while the cache could hand
    // the original out again. Disposal is paired with useGLTF.clear() on
    // unmount (see Model), which drops the cache entry at the same time.
    const root = scene.clone(true);

    root.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;

      const geometry = object.geometry as THREE.BufferGeometry;

      // Without normals the mesh renders unlit. Derive them from the geometry.
      if (!geometry.getAttribute("normal")) {
        geometry.computeVertexNormals();
      }

      const hasVertexColors = Boolean(geometry.getAttribute("color"));
      const existing = object.material as THREE.Material | THREE.Material[];
      const first = Array.isArray(existing) ? existing[0] : existing;

      const isDefaultish =
        !first ||
        (first instanceof THREE.MeshStandardMaterial &&
          first.metalness >= 0.9 &&
          !first.map);

      if (isDefaultish) {
        // Replace the unusable default with a neutral dielectric so geometry
        // and vertex colours are actually visible.
        object.material = new THREE.MeshStandardMaterial({
          color: hasVertexColors ? 0xffffff : 0xb8bfcc,
          vertexColors: hasVertexColors,
          metalness: 0.05,
          roughness: 0.62,
          side: THREE.DoubleSide,
          flatShading: false,
        });
        // The replaced material is not disposed here: the cached original still
        // references it. It is released with everything else on unmount.
      } else if (hasVertexColors && first instanceof THREE.MeshStandardMaterial) {
        first.vertexColors = true;
        first.needsUpdate = true;
      }

      object.castShadow = false;
      object.receiveShadow = false;
    });

    return root;
  }, [scene]);
}

/**
 * Centres the model at the origin and scales it into a predictable box, then
 * frames the camera to it. Generated models arrive at arbitrary scale and
 * offset, so nothing here may assume a unit-sized object.
 */
function useFraming(root: THREE.Group, controlsRef: React.RefObject<OrbitControlsImpl | null>) {
  const { camera } = useThree();

  const frame = useCallback(() => {
    const box = new THREE.Box3().setFromObject(root);
    if (box.isEmpty()) return;

    const size = box.getSize(new THREE.Vector3());
    const maxDimension = Math.max(size.x, size.y, size.z) || 1;

    // Normalise to a ~2-unit box so lighting and camera distances are stable.
    const scale = 2 / maxDimension;
    root.scale.setScalar(scale);

    // Re-measure after scaling, then centre on the origin.
    const scaledBox = new THREE.Box3().setFromObject(root);
    const center = scaledBox.getCenter(new THREE.Vector3());
    root.position.sub(center);

    const scaledSize = scaledBox.getSize(new THREE.Vector3());
    const perspective = camera as THREE.PerspectiveCamera;
    const fov = (perspective.fov * Math.PI) / 180;
    const aspect = perspective.aspect || 1;

    // Fit the bounding *box* to the frustum. Fitting the bounding sphere
    // instead (radius / sin(fov/2)) overestimates for anything non-spherical
    // and leaves the model looking small in the frame.
    const halfHeight = scaledSize.y / 2;
    const halfWidth = scaledSize.x / 2;
    const distanceForHeight = halfHeight / Math.tan(fov / 2);
    const distanceForWidth = halfWidth / (Math.tan(fov / 2) * aspect);

    // Add part of the depth so the near face is not clipped when the model is
    // rotated, then a small margin. Tuned against real Shap-E output: adding
    // the full half-depth pushes the camera back far enough that the model
    // only fills about half the frame.
    const distance =
      (Math.max(distanceForHeight, distanceForWidth) + scaledSize.z * 0.35) * 1.08;

    // A gentle three-quarter view reads better than a flat front-on shot.
    const direction = new THREE.Vector3(0.5, 0.38, 0.78).normalize();
    perspective.position.copy(direction.multiplyScalar(distance));
    perspective.near = Math.max(distance / 100, 0.01);
    perspective.far = distance * 100;
    perspective.lookAt(0, 0, 0);
    perspective.updateProjectionMatrix();

    const controls = controlsRef.current;
    if (controls) {
      controls.target.set(0, 0, 0);
      controls.minDistance = distance * 0.2;
      controls.maxDistance = distance * 6;
      controls.update();
    }
  }, [root, camera, controlsRef]);

  return frame;
}

/**
 * Neutral studio image-based lighting, generated on the GPU from three's
 * bundled RoomEnvironment.
 *
 * drei's <Environment preset> downloads an HDR from a third-party CDN at
 * runtime, which is an external dependency the product does not need and a
 * silent failure mode when it is blocked. Generating the environment locally
 * costs one render and never touches the network.
 */
function StudioEnvironment() {
  const { gl, scene } = useThree();

  useEffect(() => {
    const pmrem = new THREE.PMREMGenerator(gl);
    const room = new RoomEnvironment();
    const envMap = pmrem.fromScene(room, 0.04).texture;

    scene.environment = envMap;
    scene.environmentIntensity = 0.55;

    return () => {
      scene.environment = null;
      envMap.dispose();
      pmrem.dispose();
      room.traverse((object) => {
        if (object instanceof THREE.Mesh) {
          object.geometry?.dispose();
          const material = object.material as THREE.Material | THREE.Material[];
          if (Array.isArray(material)) material.forEach((m) => m.dispose());
          else material?.dispose();
        }
      });
    };
  }, [gl, scene]);

  return null;
}

function Model({
  url,
  controlsRef,
  handleRef,
  onLoaded,
}: {
  url: string;
  controlsRef: React.RefObject<OrbitControlsImpl | null>;
  handleRef: React.Ref<ModelViewerHandle> | undefined;
  onLoaded?: () => void;
}) {
  const { scene } = useGLTF(url);
  const prepared = usePreparedScene(scene);
  const frame = useFraming(prepared, controlsRef);

  // Held in a ref so the effect below does not depend on the callback's
  // identity. Callers pass inline arrows, which change every parent render --
  // depending on `onLoaded` directly would re-frame the camera on any parent
  // re-render (e.g. typing in the prompt box) and throw away the user's
  // current rotation and zoom.
  const onLoadedRef = useRef(onLoaded);
  onLoadedRef.current = onLoaded;

  useEffect(() => {
    frame();
    onLoadedRef.current?.();
  }, [frame]);

  useImperativeHandle(handleRef, () => ({ resetView: frame }), [frame]);

  // Free GPU memory for the previous model when the URL changes or we unmount.
  //
  // The cache entry is dropped first: `prepared` shares geometry and materials
  // with the cached scene, so disposing them while the entry is still live
  // would let a later load of the same URL receive disposed resources.
  useEffect(() => {
    return () => {
      useGLTF.clear(url);
      prepared.traverse((object) => {
        if (!(object instanceof THREE.Mesh)) return;
        object.geometry?.dispose();
        const material = object.material as THREE.Material | THREE.Material[];
        if (Array.isArray(material)) material.forEach((m) => m.dispose());
        else material?.dispose();
      });
    };
  }, [prepared, url]);

  return <primitive object={prepared} />;
}

export function ModelViewer({ url, ref, onLoaded, onError }: ModelViewerProps) {
  const controlsRef = useRef<OrbitControlsImpl | null>(null);

  return (
    <Canvas
      // Neutral studio setup: the model should read clearly, not look dramatic.
      camera={{ fov: 42, position: [2.4, 1.8, 3.2], near: 0.01, far: 1000 }}
      dpr={[1, 2]}
      gl={{ antialias: true, preserveDrawingBuffer: false }}
      onCreated={({ gl }) => {
        gl.toneMapping = THREE.ACESFilmicToneMapping;
        gl.toneMappingExposure = 1.05;
      }}
    >
      <color attach="background" args={["#0d1220"]} />

      {/*
        Neutral three-point-ish setup. Bright enough that dark generated
        vertex colours still show form, flat enough that nothing is hidden in
        dramatic shadow.
      */}
      <ambientLight intensity={0.7} />
      <directionalLight position={[4, 6, 4]} intensity={1.9} />
      <directionalLight position={[-5, 2, -3]} intensity={0.75} />
      <directionalLight position={[0, -4, 2]} intensity={0.35} />

      <StudioEnvironment />

      <Suspense fallback={null}>
        <ErrorBoundaryBridge onError={onError}>
          <Model url={url} controlsRef={controlsRef} handleRef={ref} onLoaded={onLoaded} />
        </ErrorBoundaryBridge>
      </Suspense>

      <OrbitControls
        ref={controlsRef}
        makeDefault
        enablePan
        enableZoom
        enableDamping
        dampingFactor={0.08}
        rotateSpeed={0.9}
        zoomSpeed={0.8}
      />
    </Canvas>
  );
}

/**
 * useGLTF throws inside Suspense when a fetch or parse fails. A boundary inside
 * the Canvas keeps that from tearing down the whole React tree.
 */
class ErrorBoundaryBridge extends Component<
  { children: ReactNode; onError?: (error: unknown) => void },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    this.props.onError?.(error);
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}
