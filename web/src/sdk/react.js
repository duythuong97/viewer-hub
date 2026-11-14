// Addon SDK v1 (docs/addons.md §5.3): the Hub's one React, for addon pages built with React external.
// Public API: only add exports (a removed or changed one is a new SDK major, viewer_hub/addons/manifest.py SDK_VERSION).
import * as React from "react";

export default React;
export const {
  Children, Component, Fragment, Profiler, PureComponent, StrictMode, Suspense, cloneElement, createContext,
  createElement, createRef, forwardRef, isValidElement, lazy, memo, startTransition, use, useActionState, useCallback,
  useContext, useDebugValue, useDeferredValue, useEffect, useId, useImperativeHandle, useInsertionEffect,
  useLayoutEffect, useMemo, useOptimistic, useReducer, useRef, useState, useSyncExternalStore, useTransition, version,
} = React;
