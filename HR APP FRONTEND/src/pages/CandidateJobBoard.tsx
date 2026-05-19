import React, { useState, useEffect, useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Search, MapPin, Briefcase, Building, ArrowRight, Filter, X,
  Bookmark, Flame, Zap, ExternalLink, CheckCircle2, Eye, EyeOff
} from "lucide-react";
import { toast } from "sonner";
import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent,
  DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger, DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import ResumePickerModal from "@/components/ResumePickerModal";
import { CandidateDataProvider, useCandidateData } from "@/context/CandidateDataProvider";

function CandidateJobBoardContent() {
  type StatusFilter = "all" | "applied" | "hidden";

  const [searchParams, setSearchParams] = useSearchParams();
  const { myResults, storedResumes, publicJobs, loading, fetchMyResults, fetchStoredResumes, fetchPublicJobs, invalidateResumes } = useCandidateData();
  const [search, setSearch]           = useState(searchParams.get("q") || "");
  const [savedJobs, setSavedJobs]     = useState<string[]>([]);
  const [appliedJobs, setAppliedJobs] = useState<string[]>([]);
  const [hiddenJobs, setHiddenJobs]   = useState<string[]>([]);
  const [vaultCount, setVaultCount]   = useState(0);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(() => {
    const value = searchParams.get("status");
    if (value === "applied" || value === "hidden") return value;
    return "all";
  });

  const [pickerOpen, setPickerOpen]         = useState(false);
  const [pickerJobId, setPickerJobId]       = useState("");
  const [pickerJobTitle, setPickerJobTitle] = useState("");
  const [easyApplyMode, setEasyApplyMode]   = useState(false);

  const [selectedTypes, setSelectedTypes]         = useState<string[]>(searchParams.getAll("type"));
  const [selectedLocations, setSelectedLocations] = useState<string[]>(searchParams.getAll("loc"));
  const [selectedExp, setSelectedExp]             = useState<string[]>(searchParams.getAll("exp"));
  const [selectedCompanies, setSelectedCompanies] = useState<string[]>(searchParams.getAll("comp"));
  const jobs = publicJobs;

  // FIX F-16: Sync state to URL params 
  useEffect(() => {
    setSearchParams(prev => {
      if (search) prev.set("q", search); else prev.delete("q");
      prev.delete("type"); selectedTypes.forEach(t => prev.append("type", t));
      prev.delete("loc"); selectedLocations.forEach(t => prev.append("loc", t));
      prev.delete("exp"); selectedExp.forEach(t => prev.append("exp", t));
      prev.delete("comp"); selectedCompanies.forEach(t => prev.append("comp", t));
      if (statusFilter === "all") prev.delete("status"); else prev.set("status", statusFilter);
      return prev;
    }, { replace: true });
  }, [search, selectedTypes, selectedLocations, selectedExp, selectedCompanies, statusFilter, setSearchParams]);

  const defaultCompanyName =
    localStorage.getItem("companyName") ||
    localStorage.getItem("company_name") ||
    "Your Company";

  useEffect(() => {
    setSavedJobs(JSON.parse(localStorage.getItem("saved_jobs") || "[]"));
    setAppliedJobs(JSON.parse(localStorage.getItem("applied_jobs") || "[]"));
    setHiddenJobs(JSON.parse(localStorage.getItem("hidden_jobs_candidate") || "[]"));
    fetchMyResults().catch(() => {});
    fetchStoredResumes().catch(() => {});
    fetchPublicJobs().catch(() => {});

    const POLL_MS = 30_000;
    let intervalId: ReturnType<typeof setInterval> | null = null;
    const start = () => { if (!intervalId) intervalId = setInterval(() => { fetchPublicJobs().catch(() => {}); }, POLL_MS); };
    const stop  = () => { if (intervalId) { clearInterval(intervalId); intervalId = null; } };
    const onVisibility = () => {
      if (document.visibilityState === "visible") { fetchPublicJobs().catch(() => {}); start(); } else stop();
    };
    start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [fetchMyResults, fetchStoredResumes, fetchPublicJobs]);

  useEffect(() => {
    const serverApplied = (myResults || []).map((r: any) => r.job_id).filter(Boolean);
    if (serverApplied.length > 0) {
      setAppliedJobs(serverApplied);
      localStorage.setItem("applied_jobs", JSON.stringify(serverApplied));
    }
  }, [myResults]);

  useEffect(() => {
    setVaultCount(storedResumes.length);
  }, [storedResumes]);

  const toggleSave = (e: React.MouseEvent, jobId: string) => {
    e.preventDefault(); e.stopPropagation();
    const updated = savedJobs.includes(jobId)
      ? savedJobs.filter(id => id !== jobId)
      : [...savedJobs, jobId];
    setSavedJobs(updated);
    localStorage.setItem("saved_jobs", JSON.stringify(updated));
    toast.success(updated.includes(jobId) ? "Job saved! 🔖" : "Removed from bookmarks.");
  };

  const openEasyApply = (e: React.MouseEvent, jobId: string, jobTitle: string) => {
    e.preventDefault(); e.stopPropagation();
    setPickerJobId(jobId); setPickerJobTitle(jobTitle);
    setEasyApplyMode(true); setPickerOpen(true);
  };

  const toggleHideJob = (e: React.MouseEvent, jobId: string) => {
    e.preventDefault();
    e.stopPropagation();
    const isHidden = hiddenJobs.includes(jobId);
    const updated = isHidden ? hiddenJobs.filter(id => id !== jobId) : [...hiddenJobs, jobId];
    setHiddenJobs(updated);
    localStorage.setItem("hidden_jobs_candidate", JSON.stringify(updated));
    toast.success(isHidden ? "Job unhidden." : "Job hidden from your board.");
  };

  const onApplySuccess = (jobId: string) => {
    const updated = [...appliedJobs, jobId];
    setAppliedJobs(updated);
    localStorage.setItem("applied_jobs", JSON.stringify(updated));
    invalidateResumes().catch(() => {});
  };

  const availableTypes     = useMemo(() => Array.from(new Set(jobs.map(j => j.employment_type || "Full-time"))).filter(Boolean), [jobs]);
  const availableLocations = useMemo(() => Array.from(new Set(jobs.map(j => j.location || "Remote"))).filter(Boolean), [jobs]);
  const availableCompanies = useMemo(() => Array.from(new Set(jobs.map(j => j.company || defaultCompanyName))).filter(Boolean), [jobs, defaultCompanyName]);
  const expRanges = ["Entry Level (0-2 yrs)", "Mid Level (3-5 yrs)", "Senior (5+ yrs)"];

  const toggleFilter = (setState: React.Dispatch<React.SetStateAction<string[]>>, value: string) =>
    setState(prev => prev.includes(value) ? prev.filter(v => v !== value) : [...prev, value]);

  const clearFilters = () => {
    setSelectedTypes([]); setSelectedLocations([]);
    setSelectedExp([]);   setSelectedCompanies([]);
    setStatusFilter("all");
    setSearch("");
  };

  const filteredJobs = useMemo(() => {
    const needle = search.toLowerCase();
    return jobs.filter(job => {
      const co = job.company || defaultCompanyName;
      const isHidden = hiddenJobs.includes(job.id);
      const isApplied = appliedJobs.includes(job.id);
      const matchSearch  = job.title.toLowerCase().includes(needle)
        || job.description?.toLowerCase().includes(needle)
        || job.location?.toLowerCase().includes(needle)
        || co.toLowerCase().includes(needle);
      const matchType    = selectedTypes.length === 0 || selectedTypes.includes(job.employment_type || "Full-time");
      const matchLoc     = selectedLocations.length === 0 || selectedLocations.includes(job.location || "Remote");
      const matchCompany = selectedCompanies.length === 0 || selectedCompanies.includes(co);
      let matchExp = true;
      if (selectedExp.length > 0) {
        matchExp = selectedExp.some(exp => {
          if (exp === "Entry Level (0-2 yrs)") return job.experience_min <= 2;
          if (exp === "Mid Level (3-5 yrs)")   return job.experience_min >= 3 && job.experience_min <= 5;
          if (exp === "Senior (5+ yrs)")       return job.experience_min > 5;
          return false;
        });
      }
      let matchStatus = true;
      if (statusFilter === "applied") {
        matchStatus = isApplied && !isHidden;
      } else if (statusFilter === "hidden") {
        matchStatus = isHidden;
      } else {
        matchStatus = !isHidden;
      }
      return matchSearch && matchType && matchLoc && matchCompany && matchExp && matchStatus;
    });
  }, [jobs, search, selectedTypes, selectedLocations, selectedCompanies, selectedExp, statusFilter, hiddenJobs, appliedJobs, defaultCompanyName]);

  const activeFiltersCount = selectedTypes.length + selectedLocations.length + selectedExp.length + selectedCompanies.length + (statusFilter === "all" ? 0 : 1);
  const statusLabel = statusFilter === "applied" ? "Applied" : statusFilter === "hidden" ? "Hidden" : "All";

  return (
    <div className="space-y-6 max-w-7xl mx-auto animate-in fade-in duration-500">

      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Job Board</h1>
          <p className="text-muted-foreground">Find your next opportunity.</p>
        </div>
        <div className="relative w-full md:w-96">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search by title, company, or location..."
            className="pl-9 rounded-full bg-muted/20 border-border/50"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 pb-4 border-b border-border/50">
        <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground mr-2">
          <Filter className="h-4 w-4" /> Filters:
        </div>
        {[
          { label: "Company",    state: selectedCompanies, setState: setSelectedCompanies, items: availableCompanies },
          { label: "Job Type",   state: selectedTypes,     setState: setSelectedTypes,     items: availableTypes    },
          { label: "Location",   state: selectedLocations, setState: setSelectedLocations, items: availableLocations},
          { label: "Experience", state: selectedExp,       setState: setSelectedExp,        items: expRanges         },
        ].map(({ label, state, setState, items }) => (
          <DropdownMenu key={label}>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" className="rounded-full border-dashed">
                {label}{state.length > 0 && <Badge variant="secondary" className="ml-2 px-1.5 rounded-full font-normal">{state.length}</Badge>}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-52 rounded-xl max-h-64 overflow-y-auto">
              <DropdownMenuLabel className="text-xs text-muted-foreground">Select {label}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {items.map(item => (
                <DropdownMenuCheckboxItem key={item} checked={state.includes(item)} onCheckedChange={() => toggleFilter(setState, item)}>
                  {item}
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        ))}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="rounded-full border-dashed">
              Status
              <Badge variant="secondary" className="ml-2 px-1.5 rounded-full font-normal">{statusLabel}</Badge>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-52 rounded-xl">
            <DropdownMenuLabel className="text-xs text-muted-foreground">Choose job visibility</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => setStatusFilter("all")} className="justify-between">
              <span>All visible jobs</span>
              {statusFilter === "all" && <CheckCircle2 className="h-3.5 w-3.5 text-primary" />}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setStatusFilter("applied")} className="justify-between">
              <span>Applied only</span>
              {statusFilter === "applied" && <CheckCircle2 className="h-3.5 w-3.5 text-primary" />}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setStatusFilter("hidden")} className="justify-between">
              <span>Hidden jobs ({hiddenJobs.length})</span>
              {statusFilter === "hidden" && <CheckCircle2 className="h-3.5 w-3.5 text-primary" />}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        {activeFiltersCount > 0 && (
          <Button variant="ghost" size="sm" onClick={clearFilters} className="rounded-full text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4 mr-1.5" /> Clear All
          </Button>
        )}
      </div>

      {loading.publicJobs ? (
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {[1,2,3].map(i => <Card key={i} className="h-56 animate-pulse bg-muted/20 border-border/50 rounded-3xl" />)}
        </div>
      ) : filteredJobs.length === 0 ? (
        <div className="text-center py-20 border border-dashed border-border/50 rounded-3xl bg-muted/10">
          <p className="text-lg font-medium mb-1">No matches found</p>
          <p className="text-sm text-muted-foreground mb-4">Try adjusting your filters or search query.</p>
          <Button variant="outline" className="rounded-full" onClick={clearFilters}>Reset Filters</Button>
        </div>
      ) : (
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {filteredJobs.map(job => {
            const isHot     = job.created_at ? (Date.now() - new Date(job.created_at).getTime()) < 3 * 86_400_000 : true;
            const isApplied = appliedJobs.includes(job.id);

            return (
              <Card key={job.id} className="flex flex-col hover:border-primary/30 hover:shadow-md transition-all duration-300 group relative">
                <CardHeader className="pb-4">
                  <div className="flex justify-between items-start mb-3">
                    <div className="flex flex-wrap gap-2 items-center">
                      {isHot && (
                        <Badge className="font-medium bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-900/30 dark:text-orange-400 dark:border-orange-800">
                          <Flame className="h-3 w-3 mr-1" /> Actively Hiring
                        </Badge>
                      )}
                      <Badge variant="secondary" className="font-normal">{job.employment_type || "Full-time"}</Badge>
                      {job.salary_range && (
                        <Badge className="font-medium bg-background text-foreground border-border/60">💰 {job.salary_range}</Badge>
                      )}
                    </div>
                      <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full hover:bg-muted" onClick={e => toggleSave(e, job.id)}>
                        <Bookmark className={`h-4 w-4 transition-colors ${savedJobs.includes(job.id) ? "fill-primary text-primary" : "text-muted-foreground"}`} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 rounded-full hover:bg-muted"
                        onClick={e => toggleHideJob(e, job.id)}
                        title={hiddenJobs.includes(job.id) ? "Unhide job" : "Hide job"}
                      >
                        {hiddenJobs.includes(job.id) ? (
                          <Eye className="h-4 w-4 text-muted-foreground" />
                        ) : (
                          <EyeOff className="h-4 w-4 text-muted-foreground" />
                        )}
                      </Button>
                  </div>

                  <CardTitle className="line-clamp-1 group-hover:text-primary transition-colors pr-4">{job.title}</CardTitle>

                  <div className="flex justify-between items-center mt-2">
                    <div className="flex items-center gap-2">
                      <span className="flex items-center text-sm font-medium">
                        <Building className="h-4 w-4 mr-1.5 text-muted-foreground" />{job.company || defaultCompanyName}
                      </span>
                      <Link
                        to={`/candidate/company/${job.id}`}
                        onClick={e => e.stopPropagation()}
                        className="inline-flex items-center text-[10px] font-semibold uppercase tracking-wider bg-muted/80 text-muted-foreground hover:bg-primary hover:text-primary-foreground px-2 py-0.5 rounded-full transition-colors border border-border/50 hover:border-primary"
                      >
                        About <ExternalLink className="ml-1 h-3 w-3" />
                      </Link>
                    </div>
                    <span className="text-xs text-muted-foreground whitespace-nowrap">
                      {job.created_at ? new Date(job.created_at).toLocaleDateString("en-GB", { day: "2-digit", month: "2-digit", year: "numeric" }) : "Just now"}
                    </span>
                  </div>
                </CardHeader>

                <CardContent className="flex-1 pb-4">
                  <CardDescription className="line-clamp-2 leading-relaxed mb-4">{job.description}</CardDescription>
                  <div className="space-y-2.5 text-sm font-medium text-muted-foreground">
                    <div className="flex items-center gap-2.5"><MapPin className="h-4 w-4 opacity-70" />{job.location || "Remote"}</div>
                    <div className="flex items-center gap-2.5"><Briefcase className="h-4 w-4 opacity-70" />{job.experience_min}–{job.experience_max} years experience</div>
                  </div>
                  <div className="mt-5">
                    <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Required Skills</p>
                    <div className="flex flex-wrap gap-1.5">
                      {(job.must_have_skills || []).length === 0 ? (
                        <span className="text-xs text-muted-foreground">No explicit required skills listed</span>
                      ) : (
                        <>
                          {(job.must_have_skills || []).slice(0, 4).map((s: string) => (
                            <Badge key={s} variant="outline" className="text-[10px] bg-background border-border/50">{s}</Badge>
                          ))}
                          {(job.must_have_skills || []).length > 4 && (
                            <Badge variant="outline" className="text-[10px] bg-background border-border/50 opacity-60">+{job.must_have_skills.length - 4}</Badge>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                </CardContent>

                <CardFooter className="pt-4 border-t border-border/40 bg-muted/10 gap-2">
                  {isApplied ? (
                    <div className="flex-1 flex items-center justify-center gap-2 py-2 rounded-xl bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 text-sm font-medium text-emerald-700 dark:text-emerald-400">
                      <CheckCircle2 className="h-4 w-4" /> Applied
                    </div>
                  ) : vaultCount > 0 ? (
                    <>
                      <Button
                        className="flex-1 rounded-xl bg-primary hover:bg-primary/90 shadow-sm active:scale-[0.98] transition-all"
                        onClick={e => openEasyApply(e, job.id, job.title)}
                      >
                        <Zap className="mr-1.5 h-4 w-4 fill-current" /> Easy Apply
                      </Button>
                      <Button asChild variant="outline" className="flex-1 rounded-xl transition-all">
                        <Link to={`/candidate/jobs/${job.id}`}>
                          Details <ArrowRight className="ml-1.5 h-4 w-4" />
                        </Link>
                      </Button>
                    </>
                  ) : (
                    <div className="flex-1 flex flex-col gap-1.5">
                      <Button asChild variant="default" className="w-full rounded-xl">
                        <Link to={`/candidate/jobs/${job.id}`}>
                          View & Apply <ArrowRight className="ml-1.5 h-4 w-4" />
                        </Link>
                      </Button>
                      {/* BUG FIX: was ?tab=resume — vault tab is now called "vault" */}
                      <Link
                        to="/candidate/settings?tab=vault"
                        onClick={e => e.stopPropagation()}
                        className="text-center text-[11px] text-muted-foreground hover:text-primary transition-colors"
                      >
                        Save a resume for ⚡ Easy Apply →
                      </Link>
                    </div>
                  )}
                </CardFooter>
              </Card>
            );
          })}
        </div>
      )}

      <ResumePickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        jobId={pickerJobId}
        jobTitle={pickerJobTitle}
        easyApply={easyApplyMode}
        onSuccess={() => onApplySuccess(pickerJobId)}
      />
    </div>
  );
}

export default function CandidateJobBoard() {
  return (
    <CandidateDataProvider>
      <CandidateJobBoardContent />
    </CandidateDataProvider>
  );
}
