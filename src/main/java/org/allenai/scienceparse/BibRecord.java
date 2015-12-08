package org.allenai.scienceparse;

import java.util.Calendar;
import java.util.List;
import java.util.regex.Pattern;

import lombok.Data;

@Data
public class BibRecord {
	public static final int MINYEAR = 1800;
	public static final int MAXYEAR = Calendar.getInstance().get(Calendar.YEAR) + 10;
	
	public final String title;
	public final List<String> author;
	public final String venue;
	public final Pattern citeRegEx;
	public final int year;
}