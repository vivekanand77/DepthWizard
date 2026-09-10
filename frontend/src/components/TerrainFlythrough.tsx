import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';
import {
  Mountain,
  Play,
  Pause,
  RotateCw,
  Eye,
  Layers3,
  RefreshCw,
  Maximize2,
} from 'lucide-react';
import { pipelineApi } from '../api/client';
import type { VolumeResponse } from '../types';

interface TerrainFlythroughProps {
  jobId: string;
  onBack: () => void;
}

interface FlythroughPoint {
  position: THREE.Vector3;
  target: THREE.Vector3;
}

const DEFAULT_Z_EXAGGERATION = 2.0;

const formatMetricValue = (value: number | null | undefined, suffix = 'm') => {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return 'Not available';
  }

  return `${value.toFixed(2)} ${suffix}`;
};

const disposeObject = (object: THREE.Object3D) => {
  object.traverse((node) => {
    const mesh = node as THREE.Mesh;
    if (mesh.isMesh) {
      mesh.geometry?.dispose();

      if (Array.isArray(mesh.material)) {
        mesh.material.forEach((material) => material.dispose());
      } else if (mesh.material) {
        mesh.material.dispose();
      }
    }
  });
};

const buildFlythroughPath = (bounds: THREE.Box3, zExaggeration: number): FlythroughPoint[] => {
  const size = bounds.getSize(new THREE.Vector3());
  const center = bounds.getCenter(new THREE.Vector3());
  const maxSpan = Math.max(size.x, size.y, size.z);
  const terrainHeight = Math.max(25, size.z * zExaggeration * 1.25);
  const safeHeight = Math.max(30, maxSpan * 0.75 + terrainHeight * 0.4);

  const centerTarget = new THREE.Vector3(center.x, center.y, center.z + size.z * 0.2);

  return [
    {
      position: new THREE.Vector3(center.x + size.x * 0.75, center.y - size.y * 0.85, safeHeight * 1.15),
      target: centerTarget.clone(),
    },
    {
      position: new THREE.Vector3(center.x + size.x * 0.35, center.y - size.y * 0.5, safeHeight * 0.7),
      target: new THREE.Vector3(center.x + size.x * 0.1, center.y - size.y * 0.2, center.z + size.z * 0.45),
    },
    {
      position: new THREE.Vector3(center.x - size.x * 0.05, center.y - size.y * 0.05, safeHeight * 0.45),
      target: new THREE.Vector3(center.x - size.x * 0.2, center.y + size.y * 0.1, center.z + size.z * 0.65),
    },
    {
      position: new THREE.Vector3(center.x - size.x * 0.35, center.y + size.y * 0.25, safeHeight * 0.6),
      target: new THREE.Vector3(center.x - size.x * 0.2, center.y + size.y * 0.1, center.z + size.z * 0.8),
    },
    {
      position: new THREE.Vector3(center.x + size.x * 0.05, center.y + size.y * 0.5, safeHeight * 0.5),
      target: new THREE.Vector3(center.x + size.x * 0.2, center.y + size.y * 0.1, center.z + size.z * 0.9),
    },
    {
      position: new THREE.Vector3(center.x + size.x * 0.6, center.y + size.y * 0.65, safeHeight * 0.85),
      target: centerTarget.clone(),
    },
    {
      position: new THREE.Vector3(center.x + size.x * 0.75, center.y - size.y * 0.85, safeHeight * 1.15),
      target: centerTarget.clone(),
    },
  ];
};

const applyElevationColors = (mesh: THREE.Mesh) => {
  const geometry = mesh.geometry;
  if (!geometry || !geometry.attributes.position) return;

  geometry.computeVertexNormals();

  const positions = geometry.attributes.position;
  let minZ = Infinity;
  let maxZ = -Infinity;

  for (let i = 0; i < positions.count; i += 1) {
    const z = positions.getZ(i);
    if (z < minZ) minZ = z;
    if (z > maxZ) maxZ = z;
  }

  if (!Number.isFinite(minZ) || !Number.isFinite(maxZ) || minZ === maxZ) {
    return;
  }

  const colorArray = new Float32Array(positions.count * 3);
  const lowColor = new THREE.Color('#2f9e44');
  const mediumColor = new THREE.Color('#d4a63c');
  const highColor = new THREE.Color('#e76f51');
  const extremeColor = new THREE.Color('#7a2f16');

  for (let i = 0; i < positions.count; i += 1) {
    const z = positions.getZ(i);
    const normalized = (z - minZ) / (maxZ - minZ);

    let color = new THREE.Color(lowColor);
    if (normalized < 0.33) {
      color.lerpColors(lowColor, mediumColor, normalized / 0.33);
    } else if (normalized < 0.66) {
      color.lerpColors(mediumColor, highColor, (normalized - 0.33) / 0.33);
    } else {
      color.lerpColors(highColor, extremeColor, (normalized - 0.66) / 0.34);
    }

    colorArray[i * 3] = color.r;
    colorArray[i * 3 + 1] = color.g;
    colorArray[i * 3 + 2] = color.b;
  }

  geometry.setAttribute('color', new THREE.BufferAttribute(colorArray, 3));
  (mesh.material as THREE.MeshStandardMaterial).vertexColors = true;
};

export const TerrainFlythrough: React.FC<TerrainFlythroughProps> = ({ jobId, onBack }) => {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const meshGroupRef = useRef<THREE.Group | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const flythroughStartRef = useRef<number | null>(null);
  const terrainBoundsRef = useRef<THREE.Box3 | null>(null);
  const pathRef = useRef<FlythroughPoint[]>([]);

  const [loading, setLoading] = useState(true);
  const [loadingStatus, setLoadingStatus] = useState('Loading 3D Terrain...');
  const [error, setError] = useState<string | null>(null);
  const [wireframe, setWireframe] = useState(false);
  const [autoOrbit, setAutoOrbit] = useState(false);
  const [zExaggeration, setZExaggeration] = useState(DEFAULT_Z_EXAGGERATION);
  const [flythroughActive, setFlythroughActive] = useState(false);
  const [terrainMetrics, setTerrainMetrics] = useState<VolumeResponse | null>(null);

  const resetCamera = () => {
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    const bounds = terrainBoundsRef.current;

    if (!camera || !controls || !bounds) return;

    const center = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z) || 1;

    camera.position.set(center.x + maxDim * 1.5, center.y - maxDim * 1.25, maxDim * 0.9);
    controls.target.copy(center);
    camera.lookAt(center);
    controls.update();
  };

  const updateTerrainMaterials = () => {
    if (!meshGroupRef.current) return;

    meshGroupRef.current.traverse((child) => {
      const mesh = child as THREE.Mesh;
      if (!mesh.isMesh) return;

      const material = mesh.material as THREE.MeshStandardMaterial;
      if (!material) return;

      material.wireframe = wireframe;
      material.side = THREE.DoubleSide;
    });
  };

  const loadTerrainMetrics = async () => {
    try {
      const metrics = await pipelineApi.calculateVolume(jobId);
      setTerrainMetrics(metrics);
    } catch {
      setTerrainMetrics(null);
    }
  };

  const loadTerrainMesh = async () => {
    if (!mountRef.current || !jobId) return;

    setLoading(true);
    setLoadingStatus('Loading 3D Terrain...');
    setError(null);

    try {
      const token = localStorage.getItem('depthwizard_token');
      const downloadUrl = pipelineApi.getMeshDownloadUrl(jobId, 'obj');

      let response = await fetch(downloadUrl, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });

      if (!response.ok) {
        if (response.status === 404) {
          setLoadingStatus('Generating 3D Terrain...');
          await pipelineApi.generateMesh(jobId, 'obj', 2, 1.0);

          response = await fetch(downloadUrl, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          });
        }
      }

      if (!response.ok) {
        throw new Error('Unable to load 3D terrain.');
      }

      const objText = await response.text();
      const loader = new OBJLoader();
      const parsedObj = loader.parse(objText);

      if (meshGroupRef.current) {
        while (meshGroupRef.current.children.length > 0) {
          const child = meshGroupRef.current.children[0];
          meshGroupRef.current.remove(child);
          disposeObject(child);
        }
      }

      const incomingMeshes: THREE.Mesh[] = [];
      parsedObj.traverse((child) => {
        const mesh = child as THREE.Mesh;
        if (!mesh.isMesh) return;

        mesh.geometry?.computeVertexNormals();
        mesh.material = new THREE.MeshStandardMaterial({
          color: 0xffffff,
          roughness: 0.85,
          metalness: 0.05,
          wireframe,
          side: THREE.DoubleSide,
          vertexColors: true,
        });

        applyElevationColors(mesh);
        incomingMeshes.push(mesh);
      });

      const box = new THREE.Box3().setFromObject(parsedObj);
      const center = box.getCenter(new THREE.Vector3());

      parsedObj.position.set(-center.x, -center.y, -center.z);

      const centeredBounds = new THREE.Box3().setFromObject(parsedObj);
      terrainBoundsRef.current = centeredBounds;

      if (meshGroupRef.current) {
        meshGroupRef.current.add(parsedObj);
      }

      if (meshGroupRef.current) {
        meshGroupRef.current.scale.set(1, 1, zExaggeration);
      }

      pathRef.current = buildFlythroughPath(centeredBounds, zExaggeration);

      if (cameraRef.current && controlsRef.current) {
        const size = centeredBounds.getSize(new THREE.Vector3());
        const maxDim = Math.max(size.x, size.y, size.z) || 1;
        const viewCenter = centeredBounds.getCenter(new THREE.Vector3());

        cameraRef.current.position.set(viewCenter.x + maxDim * 1.5, viewCenter.y - maxDim * 1.25, maxDim * 0.9);
        cameraRef.current.lookAt(viewCenter);
        controlsRef.current.target.copy(viewCenter);
        controlsRef.current.update();
      }

      setLoading(false);
      setError(null);
    } catch (err: any) {
      console.error('Failed to load terrain mesh:', err);
      setLoading(false);
      setError(err.message || 'Unable to load 3D terrain.');
    }
  };

  useEffect(() => {
    if (!mountRef.current || !jobId) return;

    const width = mountRef.current.clientWidth || 900;
    const height = mountRef.current.clientHeight || 560;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b1220);
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 4000);
    camera.position.set(0, -150, 120);
    camera.up.set(0, 0, 1);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    rendererRef.current = renderer;

    const mount = mountRef.current;
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.enablePan = true;
    controls.enableZoom = true;
    controls.enableRotate = true;
    controlsRef.current = controls;

    const ambientLight = new THREE.AmbientLight(0xffffff, 0.9);
    scene.add(ambientLight);

    const dirLightA = new THREE.DirectionalLight(0xffffff, 1.1);
    dirLightA.position.set(120, -120, 210);
    scene.add(dirLightA);

    const dirLightB = new THREE.DirectionalLight(0xb9dcff, 0.75);
    dirLightB.position.set(-120, 120, 120);
    scene.add(dirLightB);

    const groundGrid = new THREE.GridHelper(300, 30, 0x334155, 0x1e293b);
    groundGrid.rotation.x = Math.PI / 2;
    scene.add(groundGrid);

    const meshGroup = new THREE.Group();
    meshGroupRef.current = meshGroup;
    scene.add(meshGroup);

    const handleResize = () => {
      if (!mount || !renderer || !camera) return;
      const nextWidth = mount.clientWidth || 900;
      const nextHeight = mount.clientHeight || 560;

      camera.aspect = nextWidth / nextHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(nextWidth, nextHeight);
    };

    window.addEventListener('resize', handleResize);

    const tick = () => {
      if (controlsRef.current) {
        controlsRef.current.autoRotate = autoOrbit;
        controlsRef.current.update();
      }

      if (cameraRef.current && rendererRef.current && sceneRef.current) {
        rendererRef.current.render(sceneRef.current, cameraRef.current);
      }

      if (flythroughActive && flythroughStartRef.current !== null && pathRef.current.length > 0) {
        const elapsedSeconds = (performance.now() - flythroughStartRef.current) / 1000;
        const totalDuration = pathRef.current.length * 8;
        const wrapped = (elapsedSeconds / totalDuration) % 1;
        const progress = wrapped * (pathRef.current.length - 1);
        const index = Math.floor(progress);
        const blend = progress - index;

        const startPoint = pathRef.current[index];
        const endPoint = pathRef.current[Math.min(index + 1, pathRef.current.length - 1)];

        const nextPosition = startPoint.position.clone().lerp(endPoint.position, blend);
        const nextTarget = startPoint.target.clone().lerp(endPoint.target, blend);

        camera.position.lerp(nextPosition, 0.025);
        controlsRef.current?.target.lerp(nextTarget, 0.05);
        camera.lookAt(nextTarget);
      }

      animationFrameRef.current = requestAnimationFrame(tick);
    };

    tick();

    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }

      window.removeEventListener('resize', handleResize);
      if (controls) {
        controls.dispose();
      }

      if (mount && renderer.domElement && mount.contains(renderer.domElement)) {
        mount.removeChild(renderer.domElement);
      }

      if (meshGroupRef.current) {
        disposeObject(meshGroupRef.current);
      }

      renderer.dispose();
      scene.clear();
    };
  }, [jobId]);

  useEffect(() => {
    loadTerrainMetrics();
  }, [jobId]);

  useEffect(() => {
    loadTerrainMesh();
  }, [jobId]);

  useEffect(() => {
    updateTerrainMaterials();
  }, [wireframe]);

  useEffect(() => {
    if (meshGroupRef.current) {
      meshGroupRef.current.scale.set(1, 1, zExaggeration);
      if (terrainBoundsRef.current) {
        pathRef.current = buildFlythroughPath(terrainBoundsRef.current, zExaggeration);
      }
    }
  }, [zExaggeration]);

  useEffect(() => {
    if (controlsRef.current) {
      controlsRef.current.enableRotate = !flythroughActive;
      controlsRef.current.enablePan = !flythroughActive;
      controlsRef.current.enableZoom = !flythroughActive;
    }
  }, [flythroughActive]);

  const handleToggleFlythrough = () => {
    if (flythroughActive) {
      setFlythroughActive(false);
      return;
    }

    if (pathRef.current.length === 0 || !terrainBoundsRef.current) {
      return;
    }

    flythroughStartRef.current = performance.now();
    setFlythroughActive(true);
  };

  useEffect(() => {
    if (!flythroughActive && controlsRef.current) {
      controlsRef.current.update();
    }
  }, [flythroughActive]);

  return (
    <div className="terrain-page">
      <div className="terrain-header">
        <div>
          <p className="eyebrow">5. 3D TERRAIN</p>
          <h2>3D Terrain Flythrough</h2>
          <p className="step-desc">
            Explore your calibrated terrain model in an interactive 3D environment.
          </p>
        </div>

        <button className="btn-secondary" onClick={onBack}>
          Back to 3D Studio & Analytics
        </button>
      </div>

      <div className="terrain-viewer-shell">
        <div className="viewer-toolbar terrain-toolbar">
          <div className="viewer-controls terrain-controls">
            <button
              type="button"
              className={`btn-toolbar ${!wireframe ? 'active' : ''}`}
              onClick={() => setWireframe(false)}
            >
              <Eye className="icon-xs" />
              <span>Surface</span>
            </button>

            <button
              type="button"
              className={`btn-toolbar ${wireframe ? 'active' : ''}`}
              onClick={() => setWireframe(true)}
            >
              <Layers3 className="icon-xs" />
              <span>Wireframe</span>
            </button>

            <button
              type="button"
              className={`btn-toolbar ${autoOrbit ? 'active' : ''}`}
              onClick={() => setAutoOrbit((state) => !state)}
            >
              <RotateCw className="icon-xs" />
              <span>Orbit</span>
            </button>

            <button
              type="button"
              className="btn-toolbar"
              onClick={handleToggleFlythrough}
            >
              {flythroughActive ? <Pause className="icon-xs" /> : <Play className="icon-xs" />}
              <span>{flythroughActive ? 'Stop Flythrough' : 'Start Flythrough'}</span>
            </button>

            <button
              type="button"
              className="btn-toolbar"
              onClick={resetCamera}
            >
              <Maximize2 className="icon-xs" />
              <span>Reset View</span>
            </button>
          </div>

          <div className="terrain-zcontrol">
            <span className="terrain-zlabel">Z Exaggeration</span>
            <input
              type="range"
              min="1"
              max="5"
              step="0.1"
              value={zExaggeration}
              onChange={(event) => setZExaggeration(Number(event.target.value))}
            />
            <span className="terrain-zvalue">{zExaggeration.toFixed(1)}×</span>
          </div>
        </div>

        <div className="terrain-canvas-wrap">
          <div ref={mountRef} className="terrain-canvas" />

          {(loading || error) && (
            <div className="canvas-overlay terrain-overlay">
              {loading ? (
                <>
                  <div className="spinner" />
                  <span>{loadingStatus}</span>
                </>
              ) : (
                <>
                  <Mountain className="icon-lg" />
                  <span>{error || 'Unable to load 3D terrain.'}</span>
                  <button className="btn-primary" onClick={loadTerrainMesh}>
                    <RefreshCw className="icon-xs" />
                    <span>Generate 3D Terrain</span>
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="terrain-footer">
        <div className="terrain-metrics-grid">
          <div className="meta-card">
            <span className="meta-label">Min Elevation</span>
            <span className="meta-value">{formatMetricValue(terrainMetrics?.min_elevation_m)}</span>
          </div>

          <div className="meta-card">
            <span className="meta-label">Max Elevation</span>
            <span className="meta-value">{formatMetricValue(terrainMetrics?.max_elevation_m)}</span>
          </div>

          <div className="meta-card">
            <span className="meta-label">Mean Elevation</span>
            <span className="meta-value">{formatMetricValue(terrainMetrics?.mean_elevation_m)}</span>
          </div>

          <div className="meta-card">
            <span className="meta-label">Surface Area</span>
            <span className="meta-value">{formatMetricValue(terrainMetrics?.surface_area_m2, 'm²')}</span>
          </div>

          <div className="meta-card">
            <span className="meta-label">Planar Area</span>
            <span className="meta-value">{formatMetricValue(terrainMetrics?.true_surface_area_m2, 'm²')}</span>
          </div>

          <div className="meta-card">
            <span className="meta-label">Cut Volume</span>
            <span className="meta-value">{formatMetricValue(terrainMetrics?.cut_volume_m3, 'm³')}</span>
          </div>

          <div className="meta-card">
            <span className="meta-label">Fill Volume</span>
            <span className="meta-value">{formatMetricValue(terrainMetrics?.fill_volume_m3, 'm³')}</span>
          </div>

          <div className="meta-card">
            <span className="meta-label">Net Earthwork</span>
            <span className="meta-value">{formatMetricValue(terrainMetrics?.net_volume_m3, 'm³')}</span>
          </div>
        </div>

        <div className="terrain-legend">
          <span className="terrain-legend-title">Elevation</span>
          <div className="terrain-legend-scale">
            <span>High</span>
            <div className="terrain-legend-bar" />
            <span>Low</span>
          </div>
          <div className="terrain-legend-values">
            <span>{formatMetricValue(terrainMetrics?.min_elevation_m)}</span>
            <span className="legend-arrow">↓</span>
            <span>{formatMetricValue(terrainMetrics?.max_elevation_m)}</span>
          </div>
        </div>
      </div>

      <div className="terrain-status-row">
        <span className="terrain-status-label">Status:</span>
        <span className="terrain-status-value">
          {flythroughActive ? 'Flythrough Active' : 'Manual Exploration'}
        </span>
      </div>
    </div>
  );
};
