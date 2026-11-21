suppressPackageStartupMessages(library(survey))

inputs <- read.csv(commandArgs(trailingOnly = TRUE)[1])
design <- svydesign(
    data = inputs,
    id = ~SDMVPSU,
    strata = ~SDMVSTRA,
    weights = ~WTMEC2YR,
    nest = TRUE
)
domains <- grep("^d_", names(inputs), value = TRUE)
output <- lapply(domains, function(domain) {
    id <- substring(domain, 3)
    included <- as.logical(inputs[[domain]])
    if (any(included)) {
        estimate <- svymean(reformulate(paste0("y_", id)), subset(design, included))
        point <- unname(coef(estimate))
        error <- unname(SE(estimate))
    } else {
        point <- error <- NA_real_
    }
    data.frame(
        id = id, r_proportion = point, r_se = error,
        r_version = as.character(getRversion()),
        r_survey_version = as.character(packageVersion("survey"))
    )
})
write.csv(do.call(rbind, output), stdout(), row.names = FALSE)
