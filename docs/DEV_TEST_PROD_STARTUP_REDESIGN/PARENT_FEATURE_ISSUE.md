State: Filed live parent feature issue #4913 (`agent:blocked` validation hub).
Doc role: GitHub feature-hub pointer

# Dev/Test/Prod Startup Redesign Parent Feature Issue

GitHub issue #4913 is the authoritative validation hub. Its child execution order is #4914 → #4915 → #4916 → #4917 → #4918 → #4919. Issue #4899 is a separate P0 host-recovery prerequisite: no child may use Docker/Colima recovery or execute a live cutover until its acceptance receipt exists.
