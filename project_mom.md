Meeting Discussion — Large-Scale DEM Processing and Visualization
1. Overall Objective
We are expected to approach the project like a systems/engineering team and investigate the practical limits of processing large Digital Elevation Models (DEMs).
The main constraint is to work within the available hardware, particularly a laptop/desktop rather than relying on a large HPC setup.
We should identify the limitations and bottlenecks of current DEM-processing algorithms and determine how far they can be pushed on available hardware.
2. DEM Dataset
Download real Digital Elevation Model datasets, for example a region from the Himalayan mountain range.
We should experiment with different spatial resolutions, ranging approximately from:
1 m × 1 m
to 30 m × 30 m
The objective is to investigate how dataset size and resolution affect processing and visualization.
We should try to reach the maximum practical dataset size that can be handled by our available hardware and identify where the current approach reaches its limits.
3. Large-Data Visualization Problem
A major challenge is that very large DEM datasets cannot be rendered completely on the screen at once.
Instead of rendering the entire dataset, we need to determine how to efficiently render only the required subset of the data.
The required portion should ideally be processed/rendered on the fly based on what the user is currently viewing.
The system should therefore support efficient visualization of large datasets without requiring the entire high-resolution DEM to be loaded and rendered simultaneously.
4. Pyramid / Multi-Resolution Approach
Use a pyramid or multi-resolution representation of the DEM.
The DEM can be stored at multiple resolution levels:
Higher pyramid level → lower resolution → smaller amount of data
Lower pyramid level → higher resolution → more detailed data
As the user zooms in, the system should switch to the appropriate higher-resolution pyramid layer.
Instead of loading the entire high-resolution dataset, only the required region and resolution should be loaded.
Slope and aspect can then be computed for the required region at the required resolution.
Basic idea:
DEM
→ multiple pyramid layers
→ user zooms
→ switch to the appropriate layer
→ compute/render the required slope/aspect data
5. On-the-Fly Terrain Computation
The system should potentially support computation of terrain-related properties on demand some of the parameters possible are below:
Slope
Aspect
If possible ( Hill shade, Line of sight, Viewshed, Terrain-distance estimation)
The objective is to avoid precomputing and storing every possible derived dataset for the entire DEM. Instead, the required computation can be performed on the relevant region when needed.
6. Bottleneck Analysis
Rather than assuming that GPU acceleration is automatically the solution, we should first identify where the actual bottleneck occurs.
Potential bottlenecks include:
Dataset size
CPU/GPU computation
RAM/memory limitations
Data transfer between CPU and GPU
Rendering
Data loading/transfer to the visualization layer
We should determine the actual limiting factor for different dataset sizes and resolutions.
7. CPU/GPU Processing
Investigate the possibility of switching or distributing computation between CPU and GPU to improve visualization and processing performance.
Determine which operations are better suited to CPU and which can benefit from GPU acceleration.
GPU usage should be considered based on the actual bottleneck rather than being assumed to be the solution.
8. Prioritization of Resolution
The system should prioritize resolution based on the user's current view.
For a small geographic area, provide higher resolution and more detail.
For a large geographic area, use a lower-resolution representation so that the entire region can be rendered efficiently.
As the user zooms into a smaller area, progressively switch to higher-resolution data.
This allows the system to balance:
Area covered ↔ Resolution ↔ Processing cost ↔ Rendering performance
9. Existing Algorithms and Current Limits
Investigate the limits of the currently available DEM-processing algorithms.
Determine at what dataset size/resolution the existing approach becomes impractical.
Rather than only comparing algorithms theoretically, identify the actual bottleneck when running them on our available hardware.
10. Integration with Existing GIS Tools
Investigate whether our processing pipeline/plugin can be integrated with or used through GDAL.
QGIS is already being used/familiar, so it can be used as one of the visualization/testing environments.
The goal is not necessarily to recreate an entire GIS system, but to develop and test our large-scale processing/visualization approach within an existing ecosystem.
11. Visualization Tools
Potential tools discussed for visualization include:
QGIS
Cesium
Browser-based globe/terrain visualization
Cesium or another browser-based globe renderer could be particularly useful for demonstrating:
Large-area terrain
Zooming
Multi-resolution rendering
On-the-fly computation
Interactive slope/aspect visualization
12. Main Direction
The project therefore appears to be moving beyond simply benchmarking existing slope/aspect algorithms.
The broader goal is:
Given a very large, high-resolution DEM and limited computing resources, determine how to efficiently process and visualize only the data that is currently required, using multi-resolution/pyramid representations, on-the-fly computation, and appropriate CPU/GPU processing while identifying the actual system bottlenecks.