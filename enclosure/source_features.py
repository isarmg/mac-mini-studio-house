"""Extract mesh boundary loops directly from the unchanged USDZ input."""
from collections import Counter,defaultdict
import numpy as np


def boundaries(vertices,counts,indices):
    _,first,inverse=np.unique(np.round(vertices,4),axis=0,return_index=True,return_inverse=True)
    vertices=vertices[first];edges=Counter();position=0
    for count in counts:
        face=inverse[indices[position:position+count]];position+=count
        edges.update(tuple(sorted((int(a),int(b)))) for a,b in zip(face,np.roll(face,-1)) if a!=b)
    graph=defaultdict(set)
    for (a,b),count in edges.items():
        if count==1:graph[a].add(b);graph[b].add(a)
    loops=[];unused=set(graph)
    while unused:
        start=min(unused);path=[];current=start;previous=None
        for _ in range(len(graph)+1):
            path.append(current);unused.discard(current)
            choices=sorted(x for x in graph[current] if x!=previous)
            if not choices:break
            following=choices[0]
            if following==start:break
            previous,current=current,following
        loops.append(vertices[path])
    return loops
