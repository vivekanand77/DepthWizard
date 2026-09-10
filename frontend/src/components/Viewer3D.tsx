import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';
import { RotateCw, Maximize2, Eye, Box, Sliders, RefreshCw } from 'lucide-react';
import { pipelineApi } from '../api/client';

interface Viewer3DProps {
  jobId: string;
}

export const Viewer3D: React.FC<Viewer3DProps> = ({ jobId }) => {
  const mountRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [loadingStatus, setLoadingStatus] = useState('Generating 3D surface mesh...');
  const [error, setError] = useState<string | null>(null);
  const [wireframe, setWireframe] = useState(false);
  const [autoRotate, setAutoRotate] = useState(false);
  const [zExaggeration, setZExaggeration] = useState(1.5);
  const [vertexCount, setVertexCount] = useState<number>(0);
  const [faceCount, setFaceCount] = useState<number>(0);

  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const meshGroupRef = useRef<THREE.Group | null>(null);

  const loadMesh = async () => {
    if (!mountRef.current || !jobId) return;

    setLoading(true);
    setError(null);
    setLoadingStatus('Synthesizing 3D terrain mesh on server...');

    try {
      // Step 1: Call POST /api/v1/export/mesh to ensure mesh is generated
      await pipelineApi.generateMesh(jobId, 'obj', 2, 1.0);
      setLoadingStatus('Downloading and rendering 3D mesh...');

      // Step 2: Fetch the generated .obj file from /api/v1/export/mesh/download
      const token = localStorage.getItem('depthwizard_token');
      const downloadUrl = pipelineApi.getMeshDownloadUrl(jobId, 'obj');

      const res = await fetch(downloadUrl, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });

      if (!res.ok) {
        throw new Error(`Mesh download failed with status ${res.status}`);
      }

      const objText = await res.text();
      const loader = new OBJLoader();
      const parsedObj = loader.parse(objText);

      let totalVerts = 0;
      let totalFaces = 0;

      // Clean up previous mesh if any
      if (meshGroupRef.current) {
        while (meshGroupRef.current.children.length > 0) {
          const obj = meshGroupRef.current.children[0];
          meshGroupRef.current.remove(obj);
        }
      }

      parsedObj.traverse((child) => {
        if ((child as THREE.Mesh).isMesh) {
          const m = child as THREE.Mesh;
          const geo = m.geometry;
          if (geo) {
            geo.computeVertexNormals();
            if (geo.attributes.position) {
              totalVerts += geo.attributes.position.count;
              totalFaces += geo.index
                ? geo.index.count / 3
                : geo.attributes.position.count / 3;
            }
          }

          // Topographic terrain material
          m.material = new THREE.MeshStandardMaterial({
            color: 0x38bdf8,
            roughness: 0.4,
            metalness: 0.1,
            wireframe: wireframe,
            side: THREE.DoubleSide,
          });
        }
      });

      setVertexCount(totalVerts);
      setFaceCount(Math.round(totalFaces));

      // Center mesh around origin
      const box = new THREE.Box3().setFromObject(parsedObj);
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());

      parsedObj.position.x = -center.x;
      parsedObj.position.y = -center.y;
      parsedObj.position.z = -center.z;

      if (meshGroupRef.current) {
        meshGroupRef.current.add(parsedObj);
        meshGroupRef.current.scale.set(1, 1, zExaggeration);
      }

      const maxDim = Math.max(size.x, size.y, size.z) || 100;
      if (cameraRef.current && controlsRef.current) {
        cameraRef.current.position.set(0, -maxDim * 1.5, maxDim * 1.2);
        cameraRef.current.lookAt(0, 0, 0);
        controlsRef.current.target.set(0, 0, 0);
        controlsRef.current.update();
      }

      setLoading(false);
    } catch (err: any) {
      console.error('Failed to load OBJ:', err);
      setError(err.message || 'Unable to load 3D mesh. Verify backend connection.');
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!mountRef.current || !jobId) return;

    const width = mountRef.current.clientWidth || 800;
    const height = mountRef.current.clientHeight || 500;

    // Scene
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0f172a);
    sceneRef.current = scene;

    // Camera
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 4000);
    camera.position.set(0, -150, 120);
    camera.up.set(0, 0, 1);
    cameraRef.current = camera;

    // Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    rendererRef.current = renderer;

    const mount = mountRef.current;
    mount.appendChild(renderer.domElement);

    // Orbit Controls
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controlsRef.current = controls;

    // Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.75);
    scene.add(ambientLight);

    const dirLight1 = new THREE.DirectionalLight(0xffffff, 1.3);
    dirLight1.position.set(100, -100, 200);
    scene.add(dirLight1);

    const dirLight2 = new THREE.DirectionalLight(0x38bdf8, 0.5);
    dirLight2.position.set(-100, 100, -50);
    scene.add(dirLight2);

    // Grid Floor
    const grid = new THREE.GridHelper(300, 30, 0x334155, 0x1e293b);
    grid.rotation.x = Math.PI / 2;
    scene.add(grid);

    // Mesh Group
    const meshGroup = new THREE.Group();
    meshGroupRef.current = meshGroup;
    scene.add(meshGroup);

    // Trigger mesh synthesis & download
    loadMesh();

    // Animation Loop
    let animationFrameId: number;
    const animate = () => {
      animationFrameId = requestAnimationFrame(animate);
      if (controlsRef.current) {
        controlsRef.current.autoRotate = autoRotate;
        controlsRef.current.update();
      }
      if (rendererRef.current && sceneRef.current && cameraRef.current) {
        rendererRef.current.render(sceneRef.current, cameraRef.current);
      }
    };
    animate();

    // Resize Handler
    const handleResize = () => {
      if (!mount || !rendererRef.current || !cameraRef.current) return;
      const w = mount.clientWidth;
      const h = mount.clientHeight || 500;
      cameraRef.current.aspect = w / h;
      cameraRef.current.updateProjectionMatrix();
      rendererRef.current.setSize(w, h);
    };
    window.addEventListener('resize', handleResize);

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener('resize', handleResize);
      if (mount && renderer.domElement && mount.contains(renderer.domElement)) {
        mount.removeChild(renderer.domElement);
      }
      renderer.dispose();
    };
  }, [jobId]);

  // Handle wireframe changes
  useEffect(() => {
    if (meshGroupRef.current) {
      meshGroupRef.current.traverse((child) => {
        if ((child as THREE.Mesh).isMesh) {
          const mat = (child as THREE.Mesh).material as THREE.MeshStandardMaterial;
          if (mat) mat.wireframe = wireframe;
        }
      });
    }
  }, [wireframe]);

  // Handle vertical exaggeration
  useEffect(() => {
    if (meshGroupRef.current) {
      meshGroupRef.current.scale.set(1, 1, zExaggeration);
    }
  }, [zExaggeration]);

  const resetCamera = () => {
    if (cameraRef.current && controlsRef.current) {
      cameraRef.current.position.set(0, -150, 120);
      controlsRef.current.target.set(0, 0, 0);
      controlsRef.current.update();
    }
  };

  return (
    <div className="viewer-3d-wrapper">
      <div className="viewer-toolbar">
        <div className="viewer-stats">
          <span className="badge badge-subtle">
            <Box className="icon-xs" /> {vertexCount.toLocaleString()} Vertices
          </span>
          <span className="badge badge-subtle">
            {faceCount.toLocaleString()} Faces
          </span>
        </div>

        <div className="viewer-controls">
          <div className="z-scale-control">
            <Sliders className="icon-xs" />
            <span>Z-Scale: {zExaggeration}x</span>
            <input
              type="range"
              min="0.5"
              max="4.0"
              step="0.1"
              value={zExaggeration}
              onChange={(e) => setZExaggeration(parseFloat(e.target.value))}
            />
          </div>

          <button
            type="button"
            className={`btn-toolbar ${wireframe ? 'active' : ''}`}
            onClick={() => setWireframe(!wireframe)}
            title="Toggle Wireframe"
          >
            <Eye className="icon-xs" />
            <span>Wireframe</span>
          </button>

          <button
            type="button"
            className={`btn-toolbar ${autoRotate ? 'active' : ''}`}
            onClick={() => setAutoRotate(!autoRotate)}
            title="Toggle Auto-Rotate"
          >
            <RotateCw className="icon-xs" />
            <span>Orbit</span>
          </button>

          <button
            type="button"
            className="btn-toolbar"
            onClick={resetCamera}
            title="Reset View"
          >
            <Maximize2 className="icon-xs" />
            <span>Reset</span>
          </button>

          <button
            type="button"
            className="btn-toolbar"
            onClick={loadMesh}
            title="Reload Mesh"
          >
            <RefreshCw className="icon-xs" />
            <span>Regenerate</span>
          </button>
        </div>
      </div>

      <div className="canvas-container">
        <div ref={mountRef} className="three-mount-canvas" style={{ width: '100%', height: '100%' }} />

        {loading && (
          <div className="canvas-overlay">
            <div className="spinner"></div>
            <span>{loadingStatus}</span>
          </div>
        )}

        {error && (
          <div className="canvas-overlay">
            <span className="text-danger">{error}</span>
            <button className="btn-secondary btn-sm mt-2" onClick={loadMesh}>
              Retry Generation
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
