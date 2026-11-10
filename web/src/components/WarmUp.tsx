"use client";

import { useEffect } from "react";

import { warmUpApi } from "@/lib/api";

/** Renders nothing. Pings the API once so it is awake by the time a file has been chosen. */
export function WarmUp() {
    useEffect(() => {
        warmUpApi();
    }, []);
    return null;
}