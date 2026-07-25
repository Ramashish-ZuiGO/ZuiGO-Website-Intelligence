"use client";

import { useEffect, useState } from "react";
import { ProfileDefinition } from "@/components/metrics/types";
import { apiRequest } from "@/lib/api";

interface ProfileSelectorProps {
  websiteId: string;
  currentProfileId: string;
  onProfileChange?: (newProfileId: string) => void;
}

export function ProfileSelector({ websiteId, currentProfileId, onProfileChange }: ProfileSelectorProps) {
  const [profiles, setProfiles] = useState<ProfileDefinition[]>([]);
  const [selected, setSelected] = useState(currentProfileId);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadProfiles() {
      try {
        const data = await apiRequest<ProfileDefinition[]>("/api/v1/metadata/profiles");
        if (!cancelled) setProfiles(data);
      } catch (err) {
        if (!cancelled) console.error("Failed to load profiles", err);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }
    void loadProfiles();
    return () => { cancelled = true; };
  }, []);

  const handleChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newVal = e.target.value;
    setSelected(newVal);
    setErrorMsg(null);
    try {
      await apiRequest(`/api/v1/websites/${websiteId}/profile?profile_id=${newVal}`, {
        method: "PUT",
      });
      if (onProfileChange) {
        onProfileChange(newVal);
      }
    } catch (error) {
      console.error(error);
      setErrorMsg("Failed to update profile");
      setSelected(currentProfileId);
    }
  };

  if (isLoading) {
    return <div className="animate-pulse h-10 w-full bg-slate-100 rounded"></div>;
  }

  const selectedProfile = profiles.find(p => p.profile_id === selected);

  return (
    <div className="flex flex-col gap-2">
      <label htmlFor="profile-select" className="text-sm font-semibold text-slate-700">Evaluation Profile</label>
      <select
        id="profile-select"
        value={selected}
        onChange={handleChange}
        disabled={isLoading}
        className="w-[280px] rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
      >
        <option value="" disabled>Select a profile</option>
        {profiles.map(p => (
          <option key={p.profile_id} value={p.profile_id}>
            {p.name}
          </option>
        ))}
      </select>
      {errorMsg && <p className="text-xs text-red-600">{errorMsg}</p>}
      {selectedProfile && (
        <p className="text-xs text-slate-500 mt-1 max-w-sm">
          {selectedProfile.description}
        </p>
      )}
    </div>
  );
}
