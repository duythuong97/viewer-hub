"""Code-map viewer: the read side of code-map (graph, business docs, knowledge, MCP) over packs.

Layers, each importing only the ones below it:

    api/ (Flask routes)          mcp/ (MCP tools, stdio + HTTP)
                 \\                 /
       business, knowledge, retriever, flows, levels, storage, workspace, packs
                                    |
       contract/ (pure-Python pieces copied from code-map's extractor)
"""
