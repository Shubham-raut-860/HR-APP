import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { getMyResults, getPublicJobs, getStoredResumes, StoredResume } from "@/services/candidatePortal";
import { useAuth } from "@/context/AuthContext";

type DataKey = "myResults" | "storedResumes" | "publicJobs";

type CandidateDataContextValue = {
  myResults: any[];
  storedResumes: StoredResume[];
  publicJobs: any[];
  loading: {
    myResults: boolean;
    storedResumes: boolean;
    publicJobs: boolean;
  };
  fetchMyResults: () => Promise<void>;
  fetchStoredResumes: () => Promise<void>;
  fetchPublicJobs: () => Promise<void>;
  invalidateMyResults: () => Promise<void>;
  invalidateResumes: () => Promise<void>;
  invalidatePublicJobs: () => Promise<void>;
};

const CandidateDataContext = createContext<CandidateDataContextValue | null>(null);

type CandidateCacheEntry = {
  myResults: any[] | null;
  storedResumes: StoredResume[] | null;
  publicJobs: any[] | null;
};

const EMPTY_CACHE_ENTRY: CandidateCacheEntry = {
  myResults: null,
  storedResumes: null,
  publicJobs: null,
};

export function CandidateDataProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const userId = user?.id ?? "__anonymous__";
  const [cacheByUser, setCacheByUser] = useState<Record<string, CandidateCacheEntry>>({});
  const inFlightByUserRef = useRef<Record<string, Partial<Record<DataKey, Promise<void>>>>>({});
  const activeUserRef = useRef(userId);

  const getCacheForUser = useCallback(
    (uid: string): CandidateCacheEntry => cacheByUser[uid] ?? EMPTY_CACHE_ENTRY,
    [cacheByUser]
  );

  const [myResults, setMyResults] = useState<any[]>(() => getCacheForUser(userId).myResults ?? []);
  const [storedResumes, setStoredResumes] = useState<StoredResume[]>(() => getCacheForUser(userId).storedResumes ?? []);
  const [publicJobs, setPublicJobs] = useState<any[]>(() => getCacheForUser(userId).publicJobs ?? []);

  const [loading, setLoading] = useState({
    myResults: getCacheForUser(userId).myResults == null,
    storedResumes: getCacheForUser(userId).storedResumes == null,
    publicJobs: getCacheForUser(userId).publicJobs == null,
  });

  useEffect(() => {
    if (activeUserRef.current === userId) return;

    activeUserRef.current = userId;

    // Security guard: clear all in-memory candidate cache when auth identity changes
    // (including logout) so data cannot bleed across users in the same session.
    setCacheByUser({});
    inFlightByUserRef.current = {};
    setMyResults([]);
    setStoredResumes([]);
    setPublicJobs([]);
    setLoading({
      myResults: true,
      storedResumes: true,
      publicJobs: true,
    });
  }, [userId]);

  const runSingleFlight = useCallback(
    async <T,>(key: DataKey, fetcher: () => Promise<T>, apply: (data: T) => void) => {
      const userFlights = (inFlightByUserRef.current[userId] ??= {});
      if (userFlights[key]) return userFlights[key]!;

      const promise = (async () => {
        setLoading(prev => ({ ...prev, [key]: true }));
        try {
          const data = await fetcher();
          setCacheByUser(prev => {
            const existing = prev[userId] ?? EMPTY_CACHE_ENTRY;
            return {
              ...prev,
              [userId]: {
                ...existing,
                [key]: data as CandidateCacheEntry[DataKey],
              },
            };
          });
          apply(data);
        } finally {
          setLoading(prev => ({ ...prev, [key]: false }));
          userFlights[key] = undefined;
        }
      })();
      userFlights[key] = promise;
      return promise;
    },
    [userId]
  );

  const fetchMyResults = useCallback(async () => {
    const cached = cacheByUser[userId]?.myResults;
    if (cached != null) {
      setMyResults(cached);
      setLoading(prev => ({ ...prev, myResults: false }));
      return;
    }
    await runSingleFlight("myResults", () => getMyResults(), setMyResults);
  }, [cacheByUser, userId, runSingleFlight]);

  const fetchStoredResumes = useCallback(async () => {
    const cached = cacheByUser[userId]?.storedResumes;
    if (cached != null) {
      setStoredResumes(cached);
      setLoading(prev => ({ ...prev, storedResumes: false }));
      return;
    }
    await runSingleFlight("storedResumes", () => getStoredResumes(), setStoredResumes);
  }, [cacheByUser, userId, runSingleFlight]);

  const fetchPublicJobs = useCallback(async () => {
    const cached = cacheByUser[userId]?.publicJobs;
    if (cached != null) {
      setPublicJobs(cached);
      setLoading(prev => ({ ...prev, publicJobs: false }));
      return;
    }
    await runSingleFlight("publicJobs", () => getPublicJobs(), setPublicJobs);
  }, [cacheByUser, userId, runSingleFlight]);

  const invalidateMyResults = useCallback(async () => {
    setCacheByUser(prev => {
      const existing = prev[userId] ?? EMPTY_CACHE_ENTRY;
      return {
        ...prev,
        [userId]: {
          ...existing,
          myResults: null,
        },
      };
    });
    await runSingleFlight("myResults", () => getMyResults(), setMyResults);
  }, [userId, runSingleFlight]);

  const invalidateResumes = useCallback(async () => {
    setCacheByUser(prev => {
      const existing = prev[userId] ?? EMPTY_CACHE_ENTRY;
      return {
        ...prev,
        [userId]: {
          ...existing,
          storedResumes: null,
        },
      };
    });
    await runSingleFlight("storedResumes", () => getStoredResumes(), setStoredResumes);
  }, [userId, runSingleFlight]);

  const invalidatePublicJobs = useCallback(async () => {
    setCacheByUser(prev => {
      const existing = prev[userId] ?? EMPTY_CACHE_ENTRY;
      return {
        ...prev,
        [userId]: {
          ...existing,
          publicJobs: null,
        },
      };
    });
    await runSingleFlight("publicJobs", () => getPublicJobs(), setPublicJobs);
  }, [userId, runSingleFlight]);

  const value = useMemo<CandidateDataContextValue>(
    () => ({
      myResults,
      storedResumes,
      publicJobs,
      loading,
      fetchMyResults,
      fetchStoredResumes,
      fetchPublicJobs,
      invalidateMyResults,
      invalidateResumes,
      invalidatePublicJobs,
    }),
    [
      myResults,
      storedResumes,
      publicJobs,
      loading,
      fetchMyResults,
      fetchStoredResumes,
      fetchPublicJobs,
      invalidateMyResults,
      invalidateResumes,
      invalidatePublicJobs,
    ]
  );

  return <CandidateDataContext.Provider value={value}>{children}</CandidateDataContext.Provider>;
}

export function useCandidateData() {
  const ctx = useContext(CandidateDataContext);
  if (!ctx) {
    throw new Error("useCandidateData must be used within CandidateDataProvider");
  }
  return ctx;
}
